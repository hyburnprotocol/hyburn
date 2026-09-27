// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Test, console2} from "forge-std/Test.sol";
import {HyburnMiner} from "../src/HyburnMiner.sol";
import {HyburnToken} from "../src/HyburnToken.sol";

contract StressSimulationTest is Test {
    HyburnMiner miner;
    HyburnToken token;

    uint256 constant GENESIS = 1_800_000_000;
    uint256 constant INIT = 5_781_250_000_000;
    uint256 constant ROUND = 999;
    uint256 constant MIN = 0.000999 ether;

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

    address[] actors;
    address whale;
    address diehard;
    uint256 emptyRounds;
    uint256 expectedScheduled;
    uint256 dustTotal;
    uint256 cohortEarlyMinted;

    function _stressRound(uint256 r) internal {
        vm.warp(GENESIS + r * ROUND + 1);
        bool collapse = r >= 1500 && r < 1700;
        uint256 active = collapse ? 0 : 1 + (actors.length - 1) * (r < 600 ? r : 600) / 600;
        uint256 burnsThisRound;

        for (uint256 i = 0; i < active; ++i) {
            if (_rand(i * 7 + r) % 10 < 3) continue;
            uint256 amt = 0.05 ether + (_rand(i * 13 + r) % (1.5 ether));
            _burnAs(actors[i], amt);
            burnsThisRound++;
        }
        if (r >= 500 && r < 800) {
            (, uint128 t,) = miner.rounds(r);
            _burnAs(whale, uint256(t) * 3 / 2 + MIN);
            burnsThisRound++;
        }
        if (collapse) {
            _burnAs(diehard, MIN);
            burnsThisRound++;
        }
        if (burnsThisRound == 0) {
            emptyRounds++;
        } else {
            expectedScheduled += miner.rewardForRound(r);
        }

        vm.warp(GENESIS + (r + 1) * ROUND);
        (, uint128 total, bool created) = miner.rounds(r);
        if (!created) {
            assertEq(total, 0);
            return;
        }
        uint256 before = token.totalSupply();
        uint256 sumB;
        for (uint256 i = 0; i < actors.length; ++i) {
            uint128 b = miner.burned(r, actors[i]);
            if (b > 0) {
                sumB += b;
                miner.claim(r, actors[i]);
            }
        }
        if (miner.burned(r, whale) > 0) {
            sumB += miner.burned(r, whale);
            miner.claim(r, whale);
        }
        if (miner.burned(r, diehard) > 0) {
            sumB += miner.burned(r, diehard);
            miner.claim(r, diehard);
        }
        assertEq(sumB, total, "per-round burned sum");
        uint256 minted = token.totalSupply() - before;
        assertLe(minted, miner.rewardForRound(r), "minted <= reward");
        dustTotal += miner.rewardForRound(r) - minted;
    }

    function test_Stress_LongRunChurnWhaleCollapse() public {
        for (uint256 i = 0; i < 60; ++i) {
            actors.push(makeAddr(string(abi.encodePacked("actor", i))));
        }
        whale = makeAddr("whale");
        diehard = makeAddr("diehard");

        uint256 ROUNDS = 3000;
        for (uint256 r = 0; r < ROUNDS; ++r) {
            _stressRound(r);
        }

        assertEq(miner.nonEmptyRoundCount() + emptyRounds, ROUNDS, "created + empty == rounds");
        assertEq(token.totalSupply() + dustTotal, expectedScheduled, "minted + dust == scheduled for non-empty rounds");
        assertEq(miner.totalHypeBurned(), address(miner.burnVault()).balance);

        uint256 supply = token.totalSupply();
        uint256 top1 = token.balanceOf(whale);
        uint256 first10;
        for (uint256 i = 0; i < 10; ++i) {
            first10 += token.balanceOf(actors[i]);
        }
        uint256 die = token.balanceOf(diehard);
        console2.log("rounds %s | non-empty %s | empty %s", ROUNDS, miner.nonEmptyRoundCount(), emptyRounds);
        console2.log("supply minted (999): %s | HYPE burned (mHYPE): %s", supply / 1e9, miner.totalHypeBurned() / 1e15);
        console2.log("whale (60%% of 300 rounds) share: %s bp", top1 * 10_000 / supply);
        console2.log("first-10 joiners share: %s bp", first10 * 10_000 / supply);
        console2.log(
            "diehard (200 collapse rounds at MIN_BURN) share: %s bp for %s wei burned",
            die * 10_000 / supply,
            miner.burned(1600, diehard) * 200
        );
        console2.log("dust total: %s units", dustTotal);

        assertLt(top1 * 10_000 / supply, 700);
        assertGt(top1 * 10_000 / supply, 550);

        assertEq(die, INIT * 200);
    }

    function test_Stress_DustWalletGriefing() public {
        address u1 = makeAddr("u1");
        address u2 = makeAddr("u2");
        address u3 = makeAddr("u3");
        uint256 gBefore = _burnAs(u1, 10 ether);
        uint256 nGrief = 5000;
        for (uint256 i = 0; i < nGrief; ++i) {
            _burnAs(address(uint160(0x100000 + i)), MIN);
        }
        uint256 gAfter = _burnAs(u2, 10 ether);
        _burnAs(u3, 10 ether);
        (, uint128 total,) = miner.rounds(0);
        assertEq(total, 30 ether + nGrief * MIN);

        vm.warp(GENESIS + ROUND);
        uint256 g = gasleft();
        miner.claim(0, u1);
        g -= gasleft();
        miner.claim(0, u2);
        miner.claim(0, u3);
        assertEq(token.balanceOf(u1), INIT * 10 ether / total);
        assertEq(token.balanceOf(u2), INIT * 10 ether / total);
        assertEq(token.balanceOf(u3), INIT * 10 ether / total);
        uint256 griefMintedMax = INIT * MIN / total * nGrief;
        console2.log(
            "griefers together can claim at most %s units (%s bp of round)",
            griefMintedMax,
            griefMintedMax * 10_000 / INIT
        );
        console2.log("user burn gas before griefing %s, after %s; claim gas %s", gBefore, gAfter, g);
        assertLe(gAfter, gBefore + 5000, "burn gas independent of participant count");
        assertLt(g, 100_000);
    }

    function test_Stress_ClaimManyLarge() public {
        address u = makeAddr("u");
        uint256 R = 2000;
        for (uint256 r = 0; r < R; ++r) {
            vm.warp(GENESIS + r * ROUND + 1);
            _burnAs(u, MIN);
        }
        vm.warp(GENESIS + R * ROUND);
        uint256 maxGas;
        for (uint256 b = 0; b < R; b += 500) {
            uint256[] memory ids = new uint256[](500);
            for (uint256 i = 0; i < 500; ++i) {
                ids[i] = b + i;
            }
            uint256 g = gasleft();
            miner.claimMany(ids, u);
            g -= gasleft();
            if (g > maxGas) maxGas = g;
        }
        console2.log("claimMany(500) max gas: %s", maxGas);
        assertEq(token.balanceOf(u), INIT * R);
        assertLt(maxGas, 30_000_000, "500 claims fit in a big block");
    }

    function test_Stress_ContractCallerCannotGainAnything() public {
        Attacker a = new Attacker(miner);
        vm.deal(address(a), 10 ether);
        address honest = makeAddr("honest");
        _burnAs(honest, 1 ether);
        a.doBurn(1 ether);
        vm.warp(GENESIS + ROUND);
        a.doClaimBoth(honest);
        assertEq(token.balanceOf(address(a)), INIT / 2);
        assertEq(token.balanceOf(honest), INIT / 2);
        assertEq(a.reentered(), 0);
    }
}

contract Attacker {
    HyburnMiner immutable miner;
    uint256 public reentered;

    constructor(HyburnMiner m) {
        miner = m;
    }

    function doBurn(uint256 amt) external {
        miner.burn{value: amt}(miner.currentRoundId());
    }

    function doClaimBoth(address other) external {
        miner.claim(0, address(this));
        miner.claim(0, other);
    }

    receive() external payable {
        reentered++;
        try miner.claim(0, address(this)) {} catch {}
    }
}
