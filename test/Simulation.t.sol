// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Test, console2, stdStorage, StdStorage} from "forge-std/Test.sol";
import {HyburnMiner} from "../src/HyburnMiner.sol";
import {HyburnToken} from "../src/HyburnToken.sol";

contract SimulationTest is Test {
    using stdStorage for StdStorage;

    HyburnMiner miner;
    HyburnToken token;

    uint256 constant GENESIS = 1_800_000_000;
    uint256 constant INIT = 5_781_250_000_000;
    uint256 constant ROUND = 999;

    uint256 seed = 999;

    function setUp() public {
        vm.warp(GENESIS - 999 seconds);
        miner = new HyburnMiner();
        vm.warp(GENESIS);
        token = miner.token();
    }

    function _rand(uint256 salt) internal returns (uint256) {
        seed = uint256(keccak256(abi.encode(seed, salt)));
        return seed;
    }

    function _burnAs(address who, uint256 amount) internal returns (uint256 gasUsed) {
        vm.deal(who, who.balance + amount);
        uint256 rid = miner.currentRoundId();
        vm.prank(who);
        uint256 g = gasleft();
        miner.burn{value: amount}(rid);
        gasUsed = g - gasleft();
    }

    struct Stats {
        uint256 earlyBurned;
        uint256 sniperBurned;
        uint256 splitBurned;
        uint256 wholeBurned;
        uint256 dust;
        uint256 gasBurnMin;
        uint256 gasBurnMax;
        uint256 gasBurnSum;
        uint256 gasBurnN;
        uint256 gasClaimMax;
    }

    Stats st;
    address[] early;
    address sniper;
    address splitA;
    address splitB;
    address whole;

    uint256 constant ROUNDS = 400;
    uint256 constant N = 30;
    uint256 constant T_EQ = 20 ether;

    function _simRound(uint256 r) internal {
        vm.warp(GENESIS + r * ROUND + 1);

        uint256 active = 1 + (N - 1) * r / (ROUNDS / 2);
        if (active > N) active = N;
        for (uint256 i = 0; i < active; ++i) {
            uint256 amt = 0.1 ether + (_rand(i) % (2 ether));
            uint256 g = _burnAs(early[i], amt);
            st.earlyBurned += amt;
            st.gasBurnSum += g;
            st.gasBurnN++;
            if (g < st.gasBurnMin) st.gasBurnMin = g;
            if (g > st.gasBurnMax) st.gasBurnMax = g;
        }

        _burnAs(splitA, 0.5 ether);
        _burnAs(splitB, 0.5 ether);
        _burnAs(whole, 1 ether);
        st.splitBurned += 1 ether;
        st.wholeBurned += 1 ether;

        vm.warp(GENESIS + (r + 1) * ROUND - 1);
        (, uint128 totalNow,) = miner.rounds(r);
        if (totalNow < T_EQ) {
            uint256 x = T_EQ - totalNow;
            if (x > 8 ether) x = 8 ether;
            _burnAs(sniper, x);
            st.sniperBurned += x;
        }

        vm.warp(GENESIS + (r + 1) * ROUND);
        uint256 mintedBefore = token.totalSupply();
        for (uint256 i = 0; i < active; ++i) {
            uint256 g = gasleft();
            miner.claim(r, early[i]);
            g -= gasleft();
            if (g > st.gasClaimMax) st.gasClaimMax = g;
        }
        miner.claim(r, splitA);
        miner.claim(r, splitB);
        miner.claim(r, whole);
        if (miner.burned(r, sniper) > 0) miner.claim(r, sniper);
        st.dust += miner.rewardForRound(r) - (token.totalSupply() - mintedBefore);

        if (r % 80 == 0 || r == ROUNDS - 1) {
            (, uint128 total,) = miner.rounds(r);
            console2.log("round %s | active %s | burned (mHYPE) %s", r, active, total / 1e15);
            console2.log(
                "        999 per HYPE %s | avg mHYPE per 999 so far %s",
                INIT * 1e18 / total / 1e9,
                miner.averageBurnPerToken() / 1e15
            );
        }
    }

    function test_Sim_AdoptionCurve() public {
        for (uint256 i = 0; i < N; ++i) {
            early.push(makeAddr(string(abi.encodePacked("early", i))));
        }
        sniper = makeAddr("sniper");
        splitA = makeAddr("splitA");
        splitB = makeAddr("splitB");
        whole = makeAddr("whole");
        st.gasBurnMin = type(uint256).max;

        for (uint256 r = 0; r < ROUNDS; ++r) {
            _simRound(r);
        }

        uint256 earlyMinted;
        for (uint256 i = 0; i < N; ++i) {
            earlyMinted += token.balanceOf(early[i]);
        }
        uint256 sniperMinted = token.balanceOf(sniper);
        uint256 splitMinted = token.balanceOf(splitA) + token.balanceOf(splitB);
        uint256 wholeMinted = token.balanceOf(whole);

        console2.log("--- realized 999 per HYPE (1e9 units per 1e18 wei) ---");
        console2.log("early   : %s", earlyMinted * 1e18 / st.earlyBurned);
        console2.log("sniper  : %s", sniperMinted * 1e18 / st.sniperBurned);
        console2.log("equilib : %s", INIT * 1e18 / T_EQ);
        console2.log(
            "split   : %s   whole: %s", splitMinted * 1e18 / st.splitBurned, wholeMinted * 1e18 / st.wholeBurned
        );
        console2.log("--- accounting ---");
        console2.log("total minted (units): %s of %s scheduled", token.totalSupply(), INIT * ROUNDS);
        console2.log("dust (units): %s  (bound = participants*rounds = %s)", st.dust, (N + 4) * ROUNDS);
        console2.log("total HYPE burned (mHYPE): %s", miner.totalHypeBurned() / 1e15);
        console2.log("--- gas ---");
        console2.log("burn  min %s  avg %s  max %s", st.gasBurnMin, st.gasBurnSum / st.gasBurnN, st.gasBurnMax);
        console2.log("claim max %s", st.gasClaimMax);

        assertEq(token.totalSupply() + st.dust, INIT * ROUNDS, "minted + dust == scheduled");
        assertLe(st.dust, (N + 4) * ROUNDS, "dust bounded by participant-rounds");
        assertGe(sniperMinted * 1e18 / st.sniperBurned, INIT * 1e18 / T_EQ - 1, "sniper never below equilibrium");
        assertLe(wholeMinted - splitMinted, ROUNDS, "split loses at most 1 unit per round");
        assertEq(miner.totalHypeBurned(), address(miner.burnVault()).balance);
        assertLt(st.gasBurnMax, 150_000, "burn fits comfortably in a 3M small block");
    }

    function test_Sim_LastBlockExclusionIsLinear() public {
        address a = makeAddr("a");
        address b = makeAddr("b");
        address victim = makeAddr("victim");

        uint256 snap = vm.snapshotState();
        _burnAs(a, 3 ether);
        _burnAs(b, 5 ether);
        vm.warp(GENESIS + ROUND - 1);
        _burnAs(victim, 2 ether);
        vm.warp(GENESIS + ROUND);
        miner.claim(0, a);
        miner.claim(0, b);
        miner.claim(0, victim);
        uint256 aWith = token.balanceOf(a);
        uint256 bWith = token.balanceOf(b);
        uint256 vWith = token.balanceOf(victim);

        vm.revertToState(snap);
        _burnAs(a, 3 ether);
        _burnAs(b, 5 ether);
        vm.warp(GENESIS + ROUND);
        miner.claim(0, a);
        miner.claim(0, b);
        uint256 aWithout = token.balanceOf(a);
        uint256 bWithout = token.balanceOf(b);

        console2.log("a: with victim %s, without %s", aWith, aWithout);
        console2.log("b: with victim %s, without %s", bWith, bWithout);
        console2.log("victim would have received %s", vWith);
        assertEq(aWithout, INIT * 3 / 8);
        assertEq(bWithout, INIT * 5 / 8);
        assertEq(aWith, INIT * 3 / 10);
        assertEq(bWith, INIT * 5 / 10);

        assertApproxEqAbs(aWithout - aWith, vWith * 3 / 8, 2);
        assertApproxEqAbs(bWithout - bWith, vWith * 5 / 8, 2);
    }

    function test_Sim_FullHorizonSchedule() public {
        address m = makeAddr("miner");
        uint256 expectedTotal;
        uint256 r = 0;
        for (uint256 e = 0; e < 43; ++e) {
            uint256 seq = e * 86_400;
            stdstore.target(address(miner)).sig(miner.nonEmptyRoundCount.selector).checked_write(seq);
            vm.warp(GENESIS + r * ROUND + 1);
            _burnAs(m, 1 ether);
            vm.warp(GENESIS + (r + 1) * ROUND);
            miner.claim(r, m);
            assertEq(miner.rewardForRound(r), INIT >> e);
            expectedTotal += INIT >> e;
            r++;
        }

        stdstore.target(address(miner)).sig(miner.nonEmptyRoundCount.selector)
            .checked_write(miner.TERMINAL_SEQUENCE() - 1);
        vm.warp(GENESIS + r * ROUND + 1);
        _burnAs(m, 1 ether);
        vm.warp(GENESIS + (r + 1) * ROUND);
        miner.claim(r, m);
        expectedTotal += 1 + miner.TERMINAL_REMAINDER();
        assertTrue(miner.miningFinished());
        assertEq(token.totalSupply(), expectedTotal);
        vm.warp(GENESIS + (r + 2) * ROUND);
        vm.deal(m, 1 ether);
        uint256 rid = miner.currentRoundId();
        vm.prank(m);
        vm.expectRevert(HyburnMiner.MiningComplete.selector);
        miner.burn{value: 1 ether}(rid);

        uint256 total;
        for (uint256 e = 0; e < 43; ++e) {
            total += 86_400 * (INIT >> e);
        }
        total += miner.TERMINAL_REMAINDER();
        assertEq(total, miner.MAX_SUPPLY());
        console2.log(
            "era rewards verified 0..42, terminal remainder %s, schedule sum == cap", miner.TERMINAL_REMAINDER()
        );
    }
}
