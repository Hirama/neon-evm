//use evm::U256;
use crate::account::{/*program,*/ token, EthereumAccount};
use solana_program::{
    account_info::AccountInfo,
    entrypoint::ProgramResult,
    program_error::ProgramError,
    pubkey::Pubkey,
};
//use solana_program::program::invoke_signed;
//use spl_associated_token_account::get_associated_token_address;

struct Accounts<'a> {
    ethereum_account: EthereumAccount<'a>,
    token_balance_account: token::State<'a>,
}

pub fn process<'a>(program_id: &'a Pubkey, accounts: &'a [AccountInfo<'a>], _instruction: &[u8]) -> ProgramResult {
    solana_program::msg!("Instruction: MigrateAccount");

    let mut parsed_accounts = Accounts {
        ethereum_account: EthereumAccount::from_account(program_id, &accounts[0])?,
        token_balance_account: token::State::from_account(&accounts[1])?,
    };

    let bump_seed = validate(program_id, &parsed_accounts)?;
    execute(&mut parsed_accounts, bump_seed)
}

fn validate(_program_id: &Pubkey, accounts: &Accounts) -> Result<u8, ProgramError> {
    let bump_seed = 0;

    if accounts.token_balance_account.mint != crate::config::token_mint::id() {
        return Err!(ProgramError::InvalidArgument;
            "Account {} - expected Neon Token account",
            accounts.token_balance_account.info.key);
    }

    Ok(bump_seed)
}

fn execute(_accounts: &mut Accounts, _bump_seed: u8) -> ProgramResult {
    Ok(())
}
