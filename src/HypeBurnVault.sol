// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

/// @notice Receive-only sink. No withdrawal, owner, upgrade or selfdestruct path.
contract HypeBurnVault {
    receive() external payable {}
}
