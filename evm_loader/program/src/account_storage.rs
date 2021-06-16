use crate::{
    account_data::AccountData,
    solana_backend::{AccountStorage, SolanaBackend},
    solidity_account::SolidityAccount,
    utils::keccak256_h256,
};
use evm::backend::Apply;
use evm::{H160,  U256};
use solana_program::{
    account_info::{AccountInfo, next_account_info},
    pubkey::Pubkey,
    program_error::ProgramError,
    sysvar::{clock, clock::Clock, Sysvar},
};
use std::{
    cell::RefCell,
};

pub enum Sender {
    Ethereum (H160),
    Solana (H160),
}

#[allow(clippy::module_name_repetitions)]
pub struct ProgramAccountStorage<'a> {
    accounts: Vec<SolidityAccount<'a>>,
    aliases: RefCell<Vec<(H160, usize)>>,
    clock_account: &'a AccountInfo<'a>,
    account_metas: Vec<&'a AccountInfo<'a>>,
    contract_id: H160,
    sender: Sender,
}

impl<'a> ProgramAccountStorage<'a> {
    /// `ProgramAccountStorage` constructor
    /// 
    /// `account_infos` expectations: 
    /// 
    /// 0. contract account info
    /// 1. contract code info
    /// 2. caller or caller account info(for ether account)
    /// 3. ... other accounts (with `clock_account` in any place)
    pub fn new(program_id: &Pubkey, account_infos: &'a [AccountInfo<'a>]) -> Result<Self, ProgramError> {
        debug_print!("account_storage::new");

        let account_info_iter = &mut account_infos.iter();

        let mut accounts = Vec::with_capacity(account_infos.len());
        let mut aliases = Vec::with_capacity(account_infos.len());
        let mut account_metas = Vec::with_capacity(account_infos.len());

        let mut clock_account = None;

        let mut push_account = |sol_account: SolidityAccount<'a>, account_info: &'a AccountInfo<'a>| {
            aliases.push((sol_account.get_ether(), accounts.len()));
            accounts.push(sol_account);
            account_metas.push(account_info);
        };

        let construct_contract_account = |account_info: &'a AccountInfo<'a>, code_info: &'a AccountInfo<'a>,| -> Result<SolidityAccount<'a>, ProgramError>
        {
            if account_info.owner != program_id || code_info.owner != program_id {
                debug_print!("Invalid owner for program info/code");
                return Err(ProgramError::InvalidArgument);
            }

            let account_data = AccountData::unpack(&account_info.data.borrow())?;
            let account = account_data.get_account()?;
    
            if *code_info.key != account.code_account {
                debug_print!("code_info.key: {:?}", *code_info.key);
                debug_print!("account.code_account: {:?}", account.code_account);
                return Err(ProgramError::InvalidAccountData)
            }
    
            let code_data = code_info.data.clone();
            let code_acc = AccountData::unpack(&code_data.borrow())?;
            code_acc.get_contract()?;
    
            SolidityAccount::new(account_info.key, account_info.lamports(), account_data, Some((code_acc, code_data)))
        };

        let contract_id = {
            let program_info = next_account_info(account_info_iter)?;
            let program_code = next_account_info(account_info_iter)?;

            let contract_acc = construct_contract_account(program_info, program_code)?;
            let contract_id = contract_acc.get_ether();
            push_account(contract_acc, program_info);

            contract_id
        };

        let sender = {
            let caller_info = next_account_info(account_info_iter)?;

            if caller_info.owner == program_id {
                let account_data = AccountData::unpack(&caller_info.data.borrow())?;
                account_data.get_account()?;

                let caller_acc = SolidityAccount::new(caller_info.key, caller_info.lamports(), account_data, None)?;
                let caller_address = caller_acc.get_ether();
                push_account(caller_acc, caller_info);
                Sender::Ethereum(caller_address)
            } else {
                if !caller_info.is_signer {
                    debug_print!("Caller must be signer");
                    debug_print!("Caller pubkey: {}", &caller_info.key.to_string());

                    return Err(ProgramError::InvalidArgument);
                }

                Sender::Solana(keccak256_h256(&caller_info.key.to_bytes()).into())
            }
        };

        while let Ok(account_info) = next_account_info(account_info_iter) {
            if account_info.owner == program_id {
                let account_data = AccountData::unpack(&account_info.data.borrow())?;
                let account = match account_data {
                    AccountData::Account(ref acc) => acc,
                    _ => { continue; },
                };

                let sol_account = if account.code_account == Pubkey::new_from_array([0_u8; 32]) {
                    debug_print!("User account");
                    SolidityAccount::new(account_info.key, account_info.lamports(), account_data, None)?
                } else {
                    debug_print!("Contract account");
                    let code_info = next_account_info(account_info_iter)?;

                    construct_contract_account(account_info, code_info)?
                };

                push_account(sol_account, account_info);
            } else if clock::check_id(account_info.key) {
                debug_print!("Clock account {}", account_info.key);
                clock_account = Some(account_info);
            }
        }

        if clock_account.is_none() {
            return Err(ProgramError::NotEnoughAccountKeys);
        }

        debug_print!("Accounts was read");
        aliases.sort_by_key(|v| v.0);

        Ok(Self {
            accounts: accounts,
            aliases: RefCell::new(aliases),
            clock_account: clock_account.unwrap(),
            account_metas: account_metas,
            contract_id: contract_id,
            sender: sender,
        })
    }

    pub fn get_sender(&self) -> &Sender {
        &self.sender
    }

    pub fn get_contract_account(&self) -> Option<&SolidityAccount<'a>> {
        self.get_account(&self.contract_id)
    }

    pub fn get_caller_account(&self) -> Option<&SolidityAccount<'a>> {
        match self.sender {
            Sender::Ethereum(addr) => self.get_account(&addr),
            Sender::Solana(_addr) => None,
        }
    }

    fn find_account(&self, address: &H160) -> Option<usize> {
        let aliases = self.aliases.borrow();
        if let Ok(pos) = aliases.binary_search_by_key(&address, |v| &v.0) {
            debug_print!("Found account for {} on position {}", &address.to_string(), &pos.to_string());
            Some(aliases[pos].1)
        }
        else {
            debug_print!("Not found account for {}", &address.to_string());
            None
        }
    }

    fn get_account(&self, address: &H160) -> Option<&SolidityAccount<'a>> {
        self.find_account(address).map(|pos| &self.accounts[pos])
    }

    pub fn apply<A, I>(&mut self, values: A, _delete_empty: bool) -> Result<(), ProgramError>
    where
        A: IntoIterator<Item = Apply<I>>,
        I: IntoIterator<Item = (U256, U256)>,
    {
        let system_account = SolanaBackend::<ProgramAccountStorage>::system_account();
        let system_account_ecrecover = SolanaBackend::<ProgramAccountStorage>::system_account_ecrecover();

        for apply in values {
            match apply {
                Apply::Modify {address, basic, code, storage, reset_storage} => {
                    if (address == system_account) || (address == system_account_ecrecover) {
                        continue;
                    }
                    if let Some(pos) = self.find_account(&address) {
                        let account = &mut self.accounts[pos];
                        let account_info = &self.account_metas[pos];
                        account.update(&account_info, address, basic.nonce, basic.balance.as_u64(), &code, storage, reset_storage)?;
                    }
                    else {
                        if let Sender::Solana(addr) = self.sender {
                            if addr == address {
                                debug_print!("This is solana user, because {:?} == {:?}.", address, addr);
                                continue;
                            }
                        }
                        debug_print!("Apply can't be done. Not found account for address = {:?}.", address);
                        return Err(ProgramError::NotEnoughAccountKeys);
                    }
                }
                Apply::Delete { address: _ } => {}
            }
        }

        //for log in logs {};

        Ok(())
    }
}

impl<'a> AccountStorage for ProgramAccountStorage<'a> {    
    fn apply_to_account<U, D, F>(&self, address: &H160, d: D, f: F) -> U
    where F: FnOnce(&SolidityAccount) -> U,
          D: FnOnce() -> U
    {
        self.get_account(address).map_or_else(d, f)
    }

    fn contract(&self) -> H160 { self.contract_id }
    fn origin(&self) -> H160 {
        match self.sender {
            Sender::Ethereum(value) | Sender::Solana(value) => value,
        }
    }

    fn block_number(&self) -> U256 {
        let clock = &Clock::from_account_info(self.clock_account).unwrap();
        clock.slot.into()
    }

    fn block_timestamp(&self) -> U256 {
        let clock = &Clock::from_account_info(self.clock_account).unwrap();
        clock.unix_timestamp.into()
    }
}
