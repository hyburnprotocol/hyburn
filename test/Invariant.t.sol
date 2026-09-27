// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Test} from "forge-std/Test.sol";
import {HyburnMiner} from "../src/HyburnMiner.sol";
import {HyburnToken} from "../src/HyburnToken.sol";

contract Handler is Test {
    HyburnMiner public miner;
    HyburnToken public token;
    address[] public actors;

    uint256 public ghostTotalBurned;
    uint256[] public touched;
    mapping(uint256 => bool) public seen;
    mapping(uint256 => uint256) public ghostRoundBurned;
    mapping(uint256 => uint256) public ghostRoundMinted;
    mapping(uint256 => mapping(address => uint256)) public ghostBurned;

    uint256 public calls_burn;
    uint256 public calls_claim;
    uint256 public calls_warp;

    constructor(HyburnMiner m) {
        miner = m;
        token = m.token();
        for (uint256 i = 0; i < 8; ++i) {
            actors.push(makeAddr(string(abi.encodePacked("actor", i))));
        }
    }

    function burn(uint256 actorSeed, uint256 amount) external {
        address actor = actors[actorSeed % actors.length];
        amount = bound(amount, miner.MIN_BURN(), 10_000 ether);
        vm.deal(actor, amount);
        uint256 rid = miner.currentRoundId();
        vm.prank(actor);
        miner.burn{value: amount}(rid);
        ghostTotalBurned += amount;
        ghostRoundBurned[rid] += amount;
        ghostBurned[rid][actor] += amount;
        if (!seen[rid]) {
            seen[rid] = true;
            touched.push(rid);
        }
        calls_burn++;
    }

    function burnAndClaim(uint256 actorSeed, uint256 amount, uint256 roundSeed) external {
        address actor = actors[actorSeed % actors.length];
        amount = bound(amount, miner.MIN_BURN(), 10_000 ether);
        vm.deal(actor, amount);
        uint256 rid = miner.currentRoundId();
        uint256[] memory ids = new uint256[](touched.length == 0 ? 0 : 3);
        for (uint256 i = 0; i < ids.length; ++i) {
            ids[i] = touched[(roundSeed % touched.length + i) % touched.length];
        }
        uint256 before = token.totalSupply();

        uint256[] memory willMint = new uint256[](ids.length);
        for (uint256 i = 0; i < ids.length; ++i) {
            willMint[i] = miner.claimable(ids[i], actor);
        }
        vm.prank(actor);
        miner.burnAndClaim{value: amount}(rid, ids);
        uint256 minted = token.totalSupply() - before;
        uint256 attributed;
        for (uint256 i = 0; i < ids.length; ++i) {
            if (willMint[i] > 0 && !_dup(ids, i)) {
                ghostRoundMinted[ids[i]] += willMint[i];
                attributed += willMint[i];
            }
        }
        require(attributed == minted, "ghost attribution mismatch");
        ghostTotalBurned += amount;
        ghostRoundBurned[rid] += amount;
        ghostBurned[rid][actor] += amount;
        if (!seen[rid]) {
            seen[rid] = true;
            touched.push(rid);
        }
        calls_burn++;
        calls_claim++;
    }

    function _dup(uint256[] memory ids, uint256 i) internal pure returns (bool) {
        for (uint256 j = 0; j < i; ++j) {
            if (ids[j] == ids[i]) return true;
        }
        return false;
    }

    function burnWrongRound(uint256 actorSeed, uint256 amount, uint256 delta) external {
        address actor = actors[actorSeed % actors.length];
        amount = bound(amount, miner.MIN_BURN(), 10 ether);
        delta = bound(delta, 1, 1000);
        vm.deal(actor, amount);
        vm.prank(actor);
        try miner.burn{value: amount}(miner.currentRoundId() + delta) {
            revert("wrong round must revert");
        } catch {}
    }

    function warp(uint256 secs) external {
        secs = bound(secs, 1, 3000);
        vm.warp(block.timestamp + secs);
        calls_warp++;
    }

    function claim(uint256 actorSeed, uint256 roundSeed) external {
        if (touched.length == 0) return;
        uint256 rid = touched[roundSeed % touched.length];
        address actor = actors[actorSeed % actors.length];
        if (
            miner.claimable(rid, actor) == 0
                && !(miner.burned(rid, actor) > 0
                    && !miner.claimed(rid, actor)
                    && block.timestamp >= miner.roundEnd(rid))
        ) {
            return;
        }
        uint256 before = token.totalSupply();
        miner.claim(rid, actor);
        ghostRoundMinted[rid] += token.totalSupply() - before;
        calls_claim++;
    }

    function touchedLength() external view returns (uint256) {
        return touched.length;
    }

    function actorsLength() external view returns (uint256) {
        return actors.length;
    }
}

contract InvariantTest is Test {
    HyburnMiner miner;
    HyburnToken token;
    Handler handler;

    function setUp() public {
        vm.warp(1_800_000_000 - 999 seconds);
        miner = new HyburnMiner();
        vm.warp(1_800_000_000);
        token = miner.token();
        handler = new Handler(miner);
        targetContract(address(handler));
    }

    function invariant_SupplyNeverExceedsCap() public view {
        assertLe(token.totalSupply(), miner.MAX_SUPPLY());
    }

    function invariant_BurnAccountingMatchesVault() public view {
        assertEq(miner.totalHypeBurned(), handler.ghostTotalBurned());
        assertEq(address(miner.burnVault()).balance, handler.ghostTotalBurned());
        assertEq(address(miner).balance, 0);
    }

    function invariant_PerRoundAccounting() public view {
        uint256 n = handler.touchedLength();
        uint256 sumBurned;
        uint256 sumMinted;
        for (uint256 i = 0; i < n; ++i) {
            uint256 rid = handler.touched(i);
            (, uint128 total, bool created) = miner.rounds(rid);
            assertTrue(created);
            assertEq(total, handler.ghostRoundBurned(rid));
            assertLe(handler.ghostRoundMinted(rid), miner.rewardForRound(rid));
            uint256 perActor;
            for (uint256 a = 0; a < handler.actorsLength(); ++a) {
                address actor = handler.actors(a);
                assertEq(miner.burned(rid, actor), handler.ghostBurned(rid, actor));
                perActor += miner.burned(rid, actor);
            }
            assertEq(perActor, total);
            sumBurned += total;
            sumMinted += handler.ghostRoundMinted(rid);
        }
        assertEq(sumBurned, miner.totalHypeBurned());
        assertEq(sumMinted, token.totalSupply());
    }

    function invariant_SequenceMonotoneAndBounded() public view {
        uint256 n = handler.touchedLength();
        assertEq(miner.nonEmptyRoundCount(), n);
        assertLe(miner.nonEmptyRoundCount(), miner.TERMINAL_SEQUENCE());
        for (uint256 i = 0; i < n; ++i) {
            (uint64 seq,,) = miner.rounds(handler.touched(i));
            assertEq(seq, i);
        }
    }
}
