from sua import sua, Start

tickers = ["BLK", "BAC", "AAPL", "TM", "JPM",
           "JD", "INTU", "NVDA", "DIS", "TSLA"]

portfolio = Start(
    start_date="2019-01-01",
    portfolio=tickers,
    optimizer="EF",
    rebalance="1y"
)

test = portfolio.rebalance

sua(portfolio, rebalance=True)
