// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Test, stdStorage, StdStorage} from "forge-std/Test.sol";
import {HyburnMiner} from "../src/HyburnMiner.sol";
import {HyburnToken} from "../src/HyburnToken.sol";
import {HypeBurnVault} from "../src/HypeBurnVault.sol";

contract MinerTest is Test {
    using stdStorage for StdStorage;

    HyburnMiner miner;
    HyburnToken token;
    HypeBurnVault vault;

    address alice = makeAddr("alice");
    address bob = makeAddr("bob");
    address carol = makeAddr("carol");
    address stranger = makeAddr("stranger");

    uint256 constant MIN = 0.000999 ether;
    uint256 constant INIT = 5_781_250_000_000;
    uint256 constant H = 86_400;
    uint256 constant TERM = 3_715_200;
    uint256 constant REM = 1_209_600;
    uint256 constant MAX = 999_000_000 * 1e9;
    uint256 constant GENESIS = 1_800_000_000;

    function setUp() public {
        vm.warp(GENESIS - 999 seconds);
        miner = new HyburnMiner();
        vm.warp(GENESIS);
        token = miner.token();
        vault = miner.burnVault();
        vm.deal(alice, 1e30);
        vm.deal(bob, 1e30);
        vm.deal(carol, 1e30);
    }

    function test_StartDelay999SecondsAndGenesisBoundary() public {
        uint256 deployedAt = block.timestamp;
        HyburnMiner fresh = new HyburnMiner();
        assertEq(fresh.START_DELAY(), 999);
        assertEq(fresh.genesisTimestamp(), deployedAt + 999);
        assertEq(fresh.roundStart(0), deployedAt + 999);
        assertEq(fresh.roundEnd(0), deployedAt + 1998);

        vm.expectRevert(HyburnMiner.NotStarted.selector);
        fresh.currentRoundId();
        vm.warp(deployedAt + 998);
        vm.expectRevert(HyburnMiner.NotStarted.selector);
        fresh.previewCurrentRoundReward();
        vm.deal(alice, MIN * 3);
        vm.prank(alice);
        vm.expectRevert(HyburnMiner.NotStarted.selector);
        fresh.burn{value: MIN}(0);
        uint256[] memory ids = new uint256[](0);
        vm.prank(alice);
        vm.expectRevert(HyburnMiner.NotStarted.selector);
        fresh.burnAndClaim{value: MIN}(0, ids);
        assertEq(fresh.totalHypeBurned(), 0);

        vm.warp(deployedAt + 999);
        assertEq(fresh.currentRoundId(), 0);
        vm.prank(alice);
        fresh.burn{value: MIN}(0);
        assertEq(fresh.totalHypeBurned(), MIN);
        vm.warp(deployedAt + 1997);
        assertEq(fresh.currentRoundId(), 0);
        vm.warp(deployedAt + 1998);
        assertEq(fresh.currentRoundId(), 1);
        fresh.claim(0, alice);
        assertEq(fresh.token().balanceOf(alice), INIT);
    }

    function _setSequence(uint256 seq) internal {
        stdstore.target(address(miner)).sig(miner.nonEmptyRoundCount.selector).checked_write(seq);
    }

    function _burn(address who, uint256 amount) internal {
        uint256 rid = miner.currentRoundId();
        vm.prank(who);
        miner.burn{value: amount}(rid);
    }

    function _endRound(uint256 roundId) internal {
        vm.warp(miner.roundEnd(roundId));
    }

    function test_ScheduleSumsExactlyToCap() public view {
        uint256 sum;
        for (uint256 e = 0; e < 43; ++e) {
            sum += H * (INIT >> e);
        }
        assertEq(sum + REM, MAX, "43 eras + remainder == cap");
        assertEq(miner.rewardForSequence(TERM - 1), (INIT >> 42) + REM, "last sequence carries remainder");
        assertEq(miner.rewardForSequence(TERM), 0, "beyond terminal is zero");
        assertEq(INIT * 2 * H, MAX, "INITIAL_REWARD == MAX/(2*H)");
        assertEq(INIT >> 43, 0, "era 43 would be zero");
        assertEq(INIT >> 42, 1, "era 42 reward is 1 unit");
    }

    function test_HalvingBoundaries() public view {
        assertEq(miner.rewardForSequence(0), INIT);
        assertEq(miner.rewardForSequence(H - 1), INIT);
        assertEq(miner.rewardForSequence(H), INIT / 2);
        assertEq(miner.rewardForSequence(2 * H - 1), INIT / 2);
        assertEq(miner.rewardForSequence(2 * H), INIT / 4);
        assertEq(miner.rewardForSequence(42 * H), 1);
        assertEq(miner.rewardForSequence(TERM - 2), 1);
    }

    function test_DeploymentWiring() public view {
        assertEq(token.MINTER(), address(miner));
        assertEq(token.name(), "Hyburn");
        assertEq(token.symbol(), "HYBURN");
        assertEq(token.decimals(), 9);
        assertEq(token.totalSupply(), 0);
        assertEq(miner.genesisTimestamp(), GENESIS);
        assertEq(miner.currentRoundId(), 0);
        assertEq(miner.roundEnd(0), GENESIS + 999);
        assertEq(address(vault).code.length > 0, true);
    }

    function test_BurnBelowMinimumReverts() public {
        vm.prank(alice);
        vm.expectRevert(HyburnMiner.BurnBelowMinimum.selector);
        miner.burn{value: MIN - 1}(0);
        vm.prank(alice);
        vm.expectRevert(HyburnMiner.BurnBelowMinimum.selector);
        miner.burn{value: 0}(0);
    }

    function test_BurnAtMinimumSucceeds() public {
        _burn(alice, MIN);
        assertEq(miner.burned(0, alice), MIN);
        assertEq(miner.totalHypeBurned(), MIN);
        assertEq(address(vault).balance, MIN);
        assertEq(address(miner).balance, 0);
    }

    function test_BurnOverflowSingleTx() public {
        vm.deal(alice, uint256(type(uint128).max) + 10);
        vm.prank(alice);
        vm.expectRevert(HyburnMiner.BurnOverflow.selector);
        miner.burn{value: uint256(type(uint128).max) + 1}(0);
    }

    function test_BurnOverflowAccumulated() public {
        vm.deal(alice, uint256(type(uint128).max) + 10 ether);
        _burn(alice, type(uint128).max);
        assertEq(miner.burned(0, alice), type(uint128).max);
        vm.prank(bob);
        vm.expectRevert(HyburnMiner.BurnOverflow.selector);
        miner.burn{value: MIN}(0);
    }

    function test_RoundMismatchReverts() public {
        vm.prank(alice);
        vm.expectRevert(HyburnMiner.RoundMismatch.selector);
        miner.burn{value: 1 ether}(1);
    }

    function test_RoundBoundaryEndMinusOneEndEndPlusOne() public {
        vm.warp(GENESIS + 998);
        assertEq(miner.currentRoundId(), 0);
        _burn(alice, 1 ether);

        vm.warp(GENESIS + 999);
        assertEq(miner.currentRoundId(), 1);
        vm.prank(alice);
        vm.expectRevert(HyburnMiner.RoundMismatch.selector);
        miner.burn{value: 1 ether}(0);
        _burn(alice, 1 ether);
        assertEq(miner.burned(1, alice), 1 ether);

        vm.warp(GENESIS + 1000);
        assertEq(miner.currentRoundId(), 1);
        _burn(bob, 1 ether);
        assertEq(miner.burned(1, bob), 1 ether);
    }

    function test_EmptyRoundsDoNotConsumeSequence() public {
        _burn(alice, 1 ether);
        vm.warp(GENESIS + 999 * 5);
        _burn(alice, 1 ether);
        (uint64 seq0,,) = miner.rounds(0);
        (uint64 seq5,, bool created5) = miner.rounds(5);
        (,, bool created3) = miner.rounds(3);
        assertEq(seq0, 0);
        assertEq(seq5, 1);
        assertTrue(created5);
        assertFalse(created3);
        assertEq(miner.nonEmptyRoundCount(), 2);
        assertEq(miner.rewardForRound(3), 0);
    }

    function test_MultipleBurnsAccumulate() public {
        _burn(alice, 1 ether);
        _burn(alice, 2 ether);
        _burn(bob, 3 ether);
        (, uint128 total,) = miner.rounds(0);
        assertEq(miner.burned(0, alice), 3 ether);
        assertEq(total, 6 ether);
        assertEq(miner.totalHypeBurned(), 6 ether);
        assertEq(address(vault).balance, 6 ether);
    }

    function test_MinerRejectsPlainValueAndUnknownCalls() public {
        vm.prank(alice);
        (bool ok,) = address(miner).call{value: 1}("");
        assertFalse(ok, "no receive/fallback on Miner");
        (bool ok2,) = address(vault).call(abi.encodeWithSignature("withdraw()"));
        assertFalse(ok2, "vault has no functions");
        vm.prank(alice);
        (bool ok3,) = address(vault).call{value: 1}("");
        assertTrue(ok3, "vault accepts value");
    }

    function test_RoundCreatedEventAndReward() public {
        vm.expectEmit(true, true, false, true);
        emit HyburnMiner.RoundCreated(0, 0, INIT);
        _burn(alice, 1 ether);
        assertEq(miner.previewCurrentRoundReward(), INIT);
        assertEq(miner.previewRewardPerHype(0), INIT);
    }

    function test_ClaimBeforeEndReverts() public {
        _burn(alice, 1 ether);
        vm.warp(GENESIS + 998);
        vm.expectRevert(HyburnMiner.RoundNotEnded.selector);
        miner.claim(0, alice);
        assertEq(miner.claimable(0, alice), 0);
    }

    function test_ClaimAtExactEndSucceeds() public {
        _burn(alice, 1 ether);
        vm.warp(GENESIS + 999);
        assertEq(miner.claimable(0, alice), INIT);
        miner.claim(0, alice);
        assertEq(token.balanceOf(alice), INIT);
    }

    function test_ClaimUncreatedRoundReverts() public {
        vm.warp(GENESIS + 5000);
        vm.expectRevert(HyburnMiner.RoundNotCreated.selector);
        miner.claim(0, alice);
    }

    function test_ClaimNothingReverts() public {
        _burn(alice, 1 ether);
        _endRound(0);
        vm.expectRevert(HyburnMiner.NothingToClaim.selector);
        miner.claim(0, bob);
    }

    function test_DuplicateClaimReverts() public {
        _burn(alice, 1 ether);
        _endRound(0);
        miner.claim(0, alice);
        vm.expectRevert(HyburnMiner.AlreadyClaimed.selector);
        miner.claim(0, alice);
        assertEq(token.balanceOf(alice), INIT);
    }

    function test_ThirdPartyClaimMintsToAccountOnly() public {
        _burn(alice, 1 ether);
        _endRound(0);
        vm.prank(stranger);
        miner.claim(0, alice);
        assertEq(token.balanceOf(alice), INIT);
        assertEq(token.balanceOf(stranger), 0);
    }

    function test_SingleParticipantGetsFullReward() public {
        _burn(alice, MIN);
        _endRound(0);
        miner.claim(0, alice);
        assertEq(token.balanceOf(alice), INIT);
        assertEq(token.totalSupply(), INIT);
    }

    function test_ProRataSplit() public {
        _burn(alice, 1 ether);
        _burn(bob, 3 ether);
        _endRound(0);
        miner.claim(0, alice);
        miner.claim(0, bob);
        assertEq(token.balanceOf(alice), INIT * 1 / 4);
        assertEq(token.balanceOf(bob), INIT * 3 / 4);
        assertLe(token.totalSupply(), INIT);
        assertGe(token.totalSupply(), INIT - 2);
    }

    function test_ClaimMany() public {
        _burn(alice, 1 ether);
        vm.warp(GENESIS + 999);
        _burn(alice, 1 ether);
        vm.warp(GENESIS + 999 * 2);
        _burn(alice, 1 ether);
        vm.warp(GENESIS + 999 * 3);
        uint256[] memory ids = new uint256[](3);
        ids[0] = 0;
        ids[1] = 1;
        ids[2] = 2;
        miner.claimMany(ids, alice);
        assertEq(token.balanceOf(alice), INIT * 3);
        vm.expectRevert(HyburnMiner.AlreadyClaimed.selector);
        miner.claimMany(ids, alice);
    }

    function test_ZeroAmountClaimRecordsClaimedWithoutMint() public {
        _setSequence(42 * H);
        _burn(alice, 1 ether);
        _burn(bob, 1 ether);
        _endRound(0);
        assertEq(miner.rewardForRound(0), 1);
        assertEq(miner.claimable(0, alice), 0);
        miner.claim(0, alice);
        assertTrue(miner.claimed(0, alice));
        assertEq(token.totalSupply(), 0);
        vm.expectRevert(HyburnMiner.AlreadyClaimed.selector);
        miner.claim(0, alice);
    }

    function test_AverageBurnPerToken() public {
        assertEq(miner.averageBurnPerToken(), 0);
        _burn(alice, 5781.25 ether);
        _endRound(0);
        miner.claim(0, alice);
        assertEq(miner.averageBurnPerToken(), 1 ether);
    }

    function _ids(uint256 a, uint256 b) internal pure returns (uint256[] memory ids) {
        ids = new uint256[](2);
        ids[0] = a;
        ids[1] = b;
    }

    function test_BurnAndClaimClaimsPreviousAndBurnsCurrent() public {
        _burn(alice, 1 ether);
        vm.warp(GENESIS + 999);
        _burn(alice, 1 ether);
        vm.warp(GENESIS + 999 * 2 + 5);
        vm.prank(alice);
        miner.burnAndClaim{value: 2 ether}(2, _ids(0, 1));
        assertEq(token.balanceOf(alice), INIT * 2, "claimed rounds 0 and 1");
        assertEq(miner.burned(2, alice), 2 ether, "burned into round 2");
        assertTrue(miner.claimed(0, alice));
        assertTrue(miner.claimed(1, alice));
        assertEq(miner.totalHypeBurned(), 4 ether);
    }

    function test_BurnAndClaimSkipsUnclaimableWithoutRevert() public {
        _burn(alice, 1 ether);
        vm.warp(GENESIS + 999);
        miner.claim(0, alice);
        _burn(alice, 1 ether);
        vm.warp(GENESIS + 999 + 10);
        uint256[] memory ids = new uint256[](4);
        ids[0] = 0;
        ids[1] = 1;
        ids[2] = 7;
        ids[3] = 0;
        vm.prank(alice);
        miner.burnAndClaim{value: 1 ether}(1, ids);
        assertEq(token.balanceOf(alice), INIT, "only the earlier claim minted");
        assertEq(miner.burned(1, alice), 2 ether, "burn still went through");

        vm.prank(bob);
        miner.burnAndClaim{value: 1 ether}(1, _ids(0, 0));
        assertEq(token.balanceOf(bob), 0);
        assertEq(miner.burned(1, bob), 1 ether);
    }

    function test_BurnAndClaimBurnChecksStillApply() public {
        _burn(alice, 1 ether);
        vm.warp(GENESIS + 999);
        vm.prank(alice);
        vm.expectRevert(HyburnMiner.RoundMismatch.selector);
        miner.burnAndClaim{value: 1 ether}(0, _ids(0, 0));
        assertFalse(miner.claimed(0, alice), "revert undid nothing: claim never happened");
        vm.prank(alice);
        vm.expectRevert(HyburnMiner.BurnBelowMinimum.selector);
        miner.burnAndClaim{value: MIN - 1}(1, _ids(0, 0));
        vm.prank(alice);
        miner.burnAndClaim{value: MIN}(1, _ids(0, 0));
        assertEq(token.balanceOf(alice), INIT);
    }

    function test_BurnAndClaimOnlyClaimsForSender() public {
        _burn(alice, 1 ether);
        vm.warp(GENESIS + 999);
        vm.prank(bob);
        miner.burnAndClaim{value: 1 ether}(1, _ids(0, 0));
        assertEq(token.balanceOf(bob), 0);
        assertEq(token.balanceOf(alice), 0);
        assertFalse(miner.claimed(0, alice));
    }

    function testFuzz_BurnAndClaimEqualsSeparateCalls(uint96 a, uint96 b) public {
        a = uint96(bound(a, MIN, type(uint96).max));
        b = uint96(bound(b, MIN, type(uint96).max));
        _burn(alice, a);
        _burn(bob, 1 ether);
        vm.warp(GENESIS + 999);
        uint256 snap = vm.snapshotState();

        miner.claim(0, alice);
        _burn(alice, b);
        uint256 balSep = token.balanceOf(alice);
        uint256 burnSep = miner.burned(1, alice);
        vm.revertToState(snap);

        vm.prank(alice);
        miner.burnAndClaim{value: b}(1, _ids(0, 0));
        assertEq(token.balanceOf(alice), balSep);
        assertEq(miner.burned(1, alice), burnSep);
    }

    function test_TerminalLastRoundCarriesRemainderThenMiningComplete() public {
        _setSequence(TERM - 1);
        assertFalse(miner.miningFinished());
        assertEq(miner.previewCurrentRoundReward(), 1 + REM);

        vm.expectEmit(true, true, false, true);
        emit HyburnMiner.RoundCreated(0, uint64(TERM - 1), 1 + REM);
        vm.expectEmit(false, false, false, true);
        emit HyburnMiner.MiningFinished(0, uint64(TERM - 1));
        _burn(alice, 1 ether);

        assertTrue(miner.miningFinished());
        assertEq(miner.nonEmptyRoundCount(), TERM);

        _burn(bob, 1 ether);

        vm.warp(GENESIS + 999);
        vm.prank(alice);
        vm.expectRevert(HyburnMiner.MiningComplete.selector);
        miner.burn{value: 1 ether}(1);

        miner.claim(0, alice);
        miner.claim(0, bob);
        assertEq(token.balanceOf(alice), (1 + REM) / 2);
        assertEq(token.balanceOf(bob), (1 + REM) / 2);
        assertEq(miner.previewCurrentRoundReward(), 0);
    }

    function test_TerminalMinusTwoIsNormalEra42() public {
        _setSequence(TERM - 2);
        _burn(alice, 1 ether);
        assertEq(miner.rewardForRound(0), 1);
        assertFalse(miner.miningFinished());
    }

    function test_TokenMintOnlyMiner() public {
        vm.prank(alice);
        vm.expectRevert(HyburnToken.UnauthorizedMinter.selector);
        token.mint(alice, 1);
    }

    function test_TokenCapEnforced() public {
        vm.prank(address(miner));
        token.mint(alice, MAX);
        vm.prank(address(miner));
        vm.expectRevert(HyburnToken.CapExceeded.selector);
        token.mint(alice, 1);
        vm.prank(address(miner));
        vm.expectRevert(HyburnToken.ZeroAmount.selector);
        token.mint(alice, 0);
    }

    function test_TokenTransfer() public {
        _burn(alice, 1 ether);
        _endRound(0);
        miner.claim(0, alice);
        vm.prank(alice);
        token.transfer(bob, 100);
        assertEq(token.balanceOf(bob), 100);
        vm.prank(alice);
        token.approve(bob, 50);
        vm.prank(bob);
        token.transferFrom(alice, carol, 50);
        assertEq(token.balanceOf(carol), 50);
        assertEq(token.allowance(alice, bob), 0);
    }

    function testFuzz_ProRataConservation(uint96 a, uint96 b, uint96 c) public {
        a = uint96(bound(a, MIN, type(uint96).max));
        b = uint96(bound(b, MIN, type(uint96).max));
        c = uint96(bound(c, MIN, type(uint96).max));
        _burn(alice, a);
        _burn(bob, b);
        _burn(carol, c);
        _endRound(0);
        miner.claim(0, alice);
        miner.claim(0, bob);
        miner.claim(0, carol);
        uint256 T = uint256(a) + b + c;
        assertEq(token.balanceOf(alice), INIT * a / T);
        assertEq(token.balanceOf(bob), INIT * b / T);
        assertEq(token.balanceOf(carol), INIT * c / T);
        assertLe(token.totalSupply(), INIT);
        assertGe(token.totalSupply() + 3, INIT);
    }

    function testFuzz_SplittingNeverHelps(uint96 x, uint96 y, uint96 others) public {
        x = uint96(bound(x, MIN, type(uint96).max));
        y = uint96(bound(y, MIN, type(uint96).max));
        others = uint96(bound(others, MIN, type(uint96).max));
        address a1 = makeAddr("a1");
        address a2 = makeAddr("a2");
        vm.deal(a1, 1e30);
        vm.deal(a2, 1e30);

        uint256 snap = vm.snapshotState();
        _burn(alice, uint256(x) + y);
        _burn(bob, others);
        _endRound(0);
        miner.claim(0, alice);
        uint256 whole = token.balanceOf(alice);
        vm.revertToState(snap);
        _burn(a1, x);
        _burn(a2, y);
        _burn(bob, others);
        _endRound(0);
        miner.claim(0, a1);
        miner.claim(0, a2);
        uint256 split = token.balanceOf(a1) + token.balanceOf(a2);
        assertLe(split, whole);
        assertLe(whole - split, 1);
    }

    function testFuzz_TimingIrrelevant(uint96 amt, uint32 offset) public {
        amt = uint96(bound(amt, MIN, type(uint96).max));
        offset = uint32(bound(offset, 0, 998));
        _burn(bob, 7 ether);
        vm.warp(GENESIS + offset);
        _burn(alice, amt);
        _endRound(0);
        miner.claim(0, alice);
        assertEq(token.balanceOf(alice), INIT * amt / (uint256(amt) + 7 ether));
    }
}
