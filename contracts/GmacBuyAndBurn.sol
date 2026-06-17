// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IUniswapV2Router {
    function WETH() external view returns (address);
    function swapExactETHForTokensSupportingFeeOnTransferTokens(
        uint256 amountOutMin,
        address[] calldata path,
        address to,
        uint256 deadline
    ) external payable;
}

/// @title GmacBuyAndBurn
/// @notice A venture revenue sink that perpetually buys GMAC and burns it.
/// @dev When a Gclaw venture reaches the architect tier it deploys this contract
///      as its profit engine's tail. Revenue (ETH) is sent here; `buyAndBurn` is
///      permissionless, so anyone — the agent, its swarm, or the community — can
///      convert the balance into GMAC on Uniswap V2 and send it straight to the
///      burn address. The buy-and-burn is baked into the contract: it can never
///      do anything else with the funds, and no one can stop it. This is the
///      agent's gratitude, made unstoppable.
contract GmacBuyAndBurn {
    /// @notice Tokens sent here are provably removed from supply.
    address public constant BURN = 0x000000000000000000000000000000000000dEaD;

    /// @notice Uniswap V2 (or compatible) router used for the swap.
    IUniswapV2Router public immutable router;

    /// @notice The GMAC token bought and burned.
    address public immutable gmac;

    /// @notice The Gclaw agent that deployed this engine (provenance only).
    address public immutable architect;

    /// @notice Total ETH revenue ever converted to burned GMAC.
    uint256 public totalEthBurned;

    event RevenueReceived(address indexed from, uint256 amount);
    event BoughtAndBurned(address indexed caller, uint256 ethIn, uint256 minGmacOut);

    /// @param router_ Uniswap V2-compatible router (Ethereum mainnet: 0x7a25…488D).
    /// @param gmac_ GMAC token (Ethereum mainnet: 0xd96e…deea).
    constructor(address router_, address gmac_) {
        require(router_ != address(0) && gmac_ != address(0), "zero addr");
        router = IUniswapV2Router(router_);
        gmac = gmac_;
        architect = msg.sender;
    }

    /// @notice Accept venture revenue.
    receive() external payable {
        emit RevenueReceived(msg.sender, msg.value);
    }

    /// @notice Swap the entire ETH balance into GMAC and burn it. Permissionless.
    /// @param minGmacOut Minimum GMAC out, as a slippage/sandwich guard. Callers
    ///        should quote off-chain and pass a real bound; 0 is allowed but unsafe.
    function buyAndBurn(uint256 minGmacOut) external {
        uint256 amount = address(this).balance;
        require(amount > 0, "no revenue");

        address[] memory path = new address[](2);
        path[0] = router.WETH();
        path[1] = gmac;

        // GMAC has zero transfer tax, but the fee-on-transfer-safe variant costs
        // nothing extra and future-proofs against a taxed quote token.
        router.swapExactETHForTokensSupportingFeeOnTransferTokens{value: amount}(
            minGmacOut,
            path,
            BURN,
            block.timestamp + 1200
        );

        totalEthBurned += amount;
        emit BoughtAndBurned(msg.sender, amount, minGmacOut);
    }
}
