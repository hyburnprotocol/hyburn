// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

/// @notice Minimal ERC-20 with a fixed cap and one immutable minting authority.
/// @dev No transfer hooks, taxes, blacklist, upgrade or administrator.
contract HyburnToken {
    string public constant name = "Hyburn";
    string public constant symbol = "HYBURN";
    uint8 public constant decimals = 9;
    uint256 public constant MAX_SUPPLY = 999_000_000 * 1e9;

    address public immutable MINTER;

    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    error UnauthorizedMinter();
    error CapExceeded();
    error ZeroAmount();
    error InsufficientBalance();
    error InsufficientAllowance();
    error ZeroMinter();

    constructor(address minter) {
        if (minter == address(0)) revert ZeroMinter();
        MINTER = minter;
    }

    function mint(address to, uint256 amount) external {
        if (msg.sender != MINTER) revert UnauthorizedMinter();
        if (amount == 0) revert ZeroAmount();
        uint256 newSupply = totalSupply + amount;
        if (newSupply > MAX_SUPPLY) revert CapExceeded();
        totalSupply = newSupply;
        unchecked {
            balanceOf[to] += amount;
        }
        emit Transfer(address(0), to, amount);
    }

    function approve(address spender, uint256 value) external returns (bool) {
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }

    function transfer(address to, uint256 value) external returns (bool) {
        _transfer(msg.sender, to, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value) external returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        if (allowed != type(uint256).max) {
            if (allowed < value) revert InsufficientAllowance();
            unchecked {
                allowance[from][msg.sender] = allowed - value;
            }
        }
        _transfer(from, to, value);
        return true;
    }

    function _transfer(address from, address to, uint256 value) internal {
        uint256 bal = balanceOf[from];
        if (bal < value) revert InsufficientBalance();
        unchecked {
            balanceOf[from] = bal - value;
            balanceOf[to] += value;
        }
        emit Transfer(from, to, value);
    }
}
