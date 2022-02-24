// SPDX-License-Identifier: MIT

pragma solidity >=0.5.12;


interface IERC1155 {
//balanceOf(account, id)
//
//balanceOfBatch(accounts, ids)
//
//setApprovalForAll(operator, approved)
//
//isApprovedForAll(account, operator)
//
//safeTransferFrom(from, to, id, amount, data)

//safeBatchTransferFrom(from, to, ids, amounts, data)

    function balanceOf(address who, uint256 id) external view returns (uint256);
    function safeTransferFrom(address from, address to, uint256 value, bytes data) external returns (bool);

    event TransferSingle(address operator, address from, address to, uint256 id, uint256 value);

    
    function approveSolana(bytes32 spender, uint64 value) external returns (bool);

    event ApprovalSolana(address indexed owner, bytes32 indexed spender, uint64 value);
}



/*abstract*/ contract NeonERC1155Wrapper /*is IERC1155*/ {
    address constant NeonERC1155 = 0xff00000000000000000000000000000000000004;

    string public name;
    string public symbol;
    bytes32 public tokenMint;

    constructor(
        string memory _name,
        string memory _symbol,
        bytes32 _tokenMint
    ) {
        name = _name;
        symbol = _symbol;
        tokenMint = _tokenMint;
    }

    fallback() external {
        bytes memory call_data = abi.encodePacked(tokenMint, msg.data);
        (bool success, bytes memory result) = NeonERC1155.delegatecall(call_data);

        require(success, string(result));

        assembly {
            return(add(result, 0x20), mload(result))
        }
    }
}
