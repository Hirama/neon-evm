// #![deny(missing_docs)] // TODO #106 Write missing docs
//#![forbid(unsafe_code)]



//! An ERC20-like Token program for the Solana blockchain
#[macro_use]
mod debug;
mod error;
pub mod entrypoint;
//pub mod error;
//pub mod instruction;
//pub mod native_mint;
//pub mod processor;
//pub mod state;
mod hamt;
pub mod solana_backend;
pub mod account_data;
pub mod account_storage;
pub mod solidity_account;
mod storage_account;
pub mod instruction;
mod transaction;
mod executor;
mod executor_state;
pub mod utils;


// Export current solana-sdk types for downstream users who may also be building with a different
// solana-sdk version
pub use solana_program;

// Convert the UI representation of a token amount (using the decimals field defined in its mint)
// to the raw amount
//pub fn ui_amount_to_amount(ui_amount: f64, decimals: u8) -> u64 {
//    (ui_amount * 10_usize.pow(decimals as u32) as f64) as u64
//}

// Convert a raw amount to its UI representation (using the decimals field defined in its mint)
//pub fn amount_to_ui_amount(amount: u64, decimals: u8) -> f64 {
//    amount as f64 / 10_usize.pow(decimals as u32) as f64
//}

//solana_sdk::declare_id!("EVM1111111111111111111111111111111111111111");

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn test_evm_integration() {
    }
}
