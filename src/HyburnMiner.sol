// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {HypeBurnVault} from "./HypeBurnVault.sol";
import {HyburnToken} from "./HyburnToken.sol";

/// @notice Burns HYPE into fixed-duration rounds and mints each burner's pro-rata reward.
/// @dev No administrator, upgrade path or external reward oracle. Amounts use base units.
contract HyburnMiner {
    uint256 public constant MAX_SUPPLY = 999_000_000 * 1e9;
    uint256 public constant MIN_BURN = 0.000999 ether;
    uint256 public constant ROUND_DURATION = 999 seconds;
    uint256 public constant START_DELAY = 999 seconds;
    uint256 public constant HALVING_INTERVAL = 86_400;
    uint256 public constant INITIAL_REWARD = 5_781_250_000_000;
    uint256 public constant TERMINAL_SEQUENCE = 3_715_200;
    uint256 public constant TERMINAL_REMAINDER = 1_209_600;

    HyburnToken public immutable token;
    HypeBurnVault public immutable burnVault;
    uint256 public immutable genesisTimestamp;

    struct Round {
        uint64 miningSequence;
        uint128 totalBurned;
        bool created;
    }

    mapping(uint256 roundId => Round) public rounds;
    mapping(uint256 roundId => mapping(address account => uint128)) public burned;
    mapping(uint256 roundId => mapping(address account => bool)) public claimed;
    uint256 public nonEmptyRoundCount;
    uint256 public totalHypeBurned;

    uint256 private _entered;

    event RoundCreated(uint256 indexed roundId, uint64 indexed miningSequence, uint256 reward);
    event HypeBurned(uint256 indexed roundId, address indexed account, uint256 amount, uint128 roundTotalBurned);
    event RewardClaimed(uint256 indexed roundId, address indexed account, uint128 burned, uint256 amount);
    event MiningFinished(uint256 lastRoundId, uint64 lastMiningSequence);

    error BurnBelowMinimum();
    error BurnOverflow();
    error RoundMismatch();
    error RoundNotCreated();
    error RoundNotEnded();
    error NothingToClaim();
    error AlreadyClaimed();
    error MiningComplete();
    error BurnTransferFailed();
    error Reentrancy();
    error NotStarted();

    modifier nonReentrant() {
        if (_entered == 1) revert Reentrancy();
        _entered = 1;
        _;
        _entered = 0;
    }

    constructor() {
        // One round of notice before the first burn can be accepted.
        genesisTimestamp = block.timestamp + START_DELAY;
        burnVault = new HypeBurnVault();
        token = new HyburnToken(address(this));
    }

    function currentRoundId() public view returns (uint256) {
        if (block.timestamp < genesisTimestamp) revert NotStarted();
        return (block.timestamp - genesisTimestamp) / ROUND_DURATION;
    }

    function roundStart(uint256 roundId) public view returns (uint256) {
        return genesisTimestamp + roundId * ROUND_DURATION;
    }

    function roundEnd(uint256 roundId) public view returns (uint256) {
        return genesisTimestamp + (roundId + 1) * ROUND_DURATION;
    }

    function miningFinished() public view returns (bool) {
        return nonEmptyRoundCount == TERMINAL_SEQUENCE;
    }

    /// @dev Only non-empty rounds consume a sequence. The terminal adjustment makes
    /// the scheduled sum equal MAX_SUPPLY; per-account rounding can leave supply unminted.
    function rewardForSequence(uint256 seq) public pure returns (uint256) {
        if (seq >= TERMINAL_SEQUENCE) return 0;
        uint256 r = INITIAL_REWARD >> (seq / HALVING_INTERVAL);
        if (seq == TERMINAL_SEQUENCE - 1) r += TERMINAL_REMAINDER;
        return r;
    }

    function rewardForRound(uint256 roundId) public view returns (uint256) {
        Round storage r = rounds[roundId];
        if (!r.created) return 0;
        return rewardForSequence(r.miningSequence);
    }

    function previewCurrentRoundReward() external view returns (uint256) {
        Round storage r = rounds[currentRoundId()];
        if (r.created) return rewardForSequence(r.miningSequence);
        return rewardForSequence(nonEmptyRoundCount);
    }

    function previewRewardPerHype(uint256 roundId) external view returns (uint256) {
        Round storage r = rounds[roundId];
        if (!r.created || r.totalBurned == 0) return 0;
        return rewardForSequence(r.miningSequence) * 1e18 / r.totalBurned;
    }

    /// @notice Historical burn cost per minted token, not a redemption or market price.
    function averageBurnPerToken() external view returns (uint256) {
        uint256 supply = token.totalSupply();
        if (supply == 0) return 0;
        return totalHypeBurned * 1e9 / supply;
    }

    function claimable(uint256 roundId, address account) external view returns (uint256) {
        Round storage r = rounds[roundId];
        if (!r.created || block.timestamp < roundEnd(roundId)) return 0;
        if (claimed[roundId][account]) return 0;
        uint128 b = burned[roundId][account];
        if (b == 0) return 0;
        return rewardForSequence(r.miningSequence) * b / r.totalBurned;
    }

    /// @param expectedRoundId Revert if inclusion occurs in a different round.
    function burn(uint256 expectedRoundId) external payable nonReentrant {
        _burn(expectedRoundId);
    }

    /// @dev Skip unclaimable entries, including claims raced by a third party, so they
    /// cannot invalidate an otherwise valid burn. The burn and claims remain atomic.
    function burnAndClaim(uint256 expectedRoundId, uint256[] calldata claimRoundIds) external payable nonReentrant {
        _burn(expectedRoundId);
        uint256 n = claimRoundIds.length;
        for (uint256 i = 0; i < n; ++i) {
            uint256 rid = claimRoundIds[i];
            Round storage r = rounds[rid];
            if (!r.created || block.timestamp < roundEnd(rid)) continue;
            if (burned[rid][msg.sender] == 0 || claimed[rid][msg.sender]) continue;
            _claim(rid, msg.sender);
        }
    }

    function _burn(uint256 expectedRoundId) internal {
        if (msg.value < MIN_BURN) revert BurnBelowMinimum();
        if (msg.value > type(uint128).max) revert BurnOverflow();

        uint256 roundId = currentRoundId();
        if (roundId != expectedRoundId) revert RoundMismatch();

        Round storage r = rounds[roundId];
        if (!r.created) {
            uint256 count = nonEmptyRoundCount;
            if (count >= TERMINAL_SEQUENCE) revert MiningComplete();

            // count < TERMINAL_SEQUENCE (3,715,200), so the cast cannot truncate.
            uint64 seq = uint64(count);
            r.miningSequence = seq;
            r.created = true;
            nonEmptyRoundCount = count + 1;
            emit RoundCreated(roundId, seq, rewardForSequence(seq));
            if (count + 1 == TERMINAL_SEQUENCE) emit MiningFinished(roundId, seq);
        }

        uint256 newTotal = uint256(r.totalBurned) + msg.value;
        if (newTotal > type(uint128).max) revert BurnOverflow();

        // Both the cumulative total and msg.value have been checked against uint128.max.
        uint128 newTotal128 = uint128(newTotal);

        uint128 value128 = uint128(msg.value);
        r.totalBurned = newTotal128;

        // Each account's cumulative burn is bounded by this round's total.
        burned[roundId][msg.sender] += value128;
        totalHypeBurned += msg.value;

        emit HypeBurned(roundId, msg.sender, msg.value, newTotal128);

        (bool ok,) = address(burnVault).call{value: msg.value}("");
        if (!ok) revert BurnTransferFailed();
    }

    /// @notice Anyone can submit a claim; rewards are always minted to account.
    function claim(uint256 roundId, address account) external nonReentrant {
        _claim(roundId, account);
    }

    /// @dev Unlike burnAndClaim, an invalid or duplicate entry reverts the entire batch.
    function claimMany(uint256[] calldata roundIds, address account) external nonReentrant {
        uint256 n = roundIds.length;
        for (uint256 i = 0; i < n; ++i) {
            _claim(roundIds[i], account);
        }
    }

    function _claim(uint256 roundId, address account) internal {
        Round storage r = rounds[roundId];
        if (!r.created) revert RoundNotCreated();
        if (block.timestamp < roundEnd(roundId)) revert RoundNotEnded();
        uint128 b = burned[roundId][account];
        if (b == 0) revert NothingToClaim();
        if (claimed[roundId][account]) revert AlreadyClaimed();

        claimed[roundId][account] = true;

        // reward < 2^43 and b < 2^128: the product fits uint256. Division rounds down;
        // dust stays unminted. Even a zero payout is recorded to prevent repeat claims.
        uint256 amount = rewardForSequence(r.miningSequence) * b / r.totalBurned;
        if (amount > 0) token.mint(account, amount);
        emit RewardClaimed(roundId, account, b, amount);
    }
}
