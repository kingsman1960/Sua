import numpy as np
import pandas as pd
import datetime as dt
import quantstats as qs
from IPython.display import display
import matplotlib.pyplot as plt
import copy
import yfinance as yf
from fpdf import FPDF
import warnings

# Using Python library with performance and risk statistics commonly used in quantitative finance.
from empyrical import (
    cagr,
    cum_returns,
    stability_of_timeseries,
    max_drawdown,
    sortino_ratio,
    alpha_beta,
    tail_ratio,
)

# PyPortfolioOpt is a library that implements portfolio optimization methods, including classical mean-variance optimization techniques and Black-Litterman allocation, as well as more recent developments in the field like shrinkage and Hierarchical Risk Parity.
from pypfopt import (
    EfficientFrontier,
    risk_models,
    expected_returns,
    HRPOpt,
    objective_functions,
    black_litterman,
    BlackLittermanModel,
)

# Importing prediction models, metrics and logging
from prophet import Prophet
from darts.models import*
from darts import TimeSeries
from darts.utils.missing_values import fill_missing_values
from darts.metrics import mape, mase
import logging

warnings.filterwarnings("ignore")

TODAY = dt.date.today()
BENCHMARK = ["SPY"]
DAYS_IN_YEAR = 365

rebalance_periods = {
    "daily": DAYS_IN_YEAR / 365,
    "weekly": DAYS_IN_YEAR / 52,
    "monthly": DAYS_IN_YEAR / 12,
    "month": DAYS_IN_YEAR / 12,
    "m": DAYS_IN_YEAR / 12,
    "quarterly": DAYS_IN_YEAR / 4,
    "quarter": DAYS_IN_YEAR / 4,
    "q": DAYS_IN_YEAR / 4,
    "6m": DAYS_IN_YEAR / 2,
    "2q": DAYS_IN_YEAR / 2,
    "1y": DAYS_IN_YEAR,
    "year": DAYS_IN_YEAR,
    "y": DAYS_IN_YEAR,
    "2y": DAYS_IN_YEAR * 2,
}


class Start:
    def __init__(
        self,
        start_date,
        portfolio,
        weights=None,
        rebalance=None,
        benchmark=None,
        end_date=TODAY,
        optimizer=None,
        max_vol=0.15,
        diversification=1,
        # confidences=None,
        # view=None,
        min_weights=None,
        max_weights=None,
        risk_manager=None,
        data=None,
    ):
        if benchmark is None:
            benchmark = BENCHMARK

        self.start_date = start_date
        self.end_date = end_date
        self.portfolio = portfolio
        self.weights = weights
        self.benchmark = benchmark
        self.optimizer = optimizer
        self.rebalance = rebalance
        self.max_vol = max_vol
        self.diversification = diversification
        self.max_weights = max_weights
        self.min_weights = min_weights
        self.risk_manager = risk_manager
        self.data = data

        optimizers = {
            "EF": efficient_frontier,
            "MEANVAR": mean_var,
            "HRP": hrp,
            "MINVAR": min_var,
        }
        if self.optimizer is None and self.weights is None:
            self.weights = [1.0 / len(self.portfolio)] * len(self.portfolio)
        elif self.optimizer in optimizers.keys():
            if self.optimizer == "MEANVAR":
                self.weights = optimizers.get(self.optimizer)(
                    self, vol_max=max_vol, perf=False)
            else:
                self.weights = optimizers.get(self.optimizer)(self, perf=False)

        if self.rebalance is not None:
            self.rebalance = make_rebalance(
                self.start_date,
                self.end_date,
                self.optimizer,
                self.portfolio,
                self.rebalance,
                self.weights,
                self.max_vol,
                self.diversification,
                self.min_weights,
                self.max_weights,
            )


def get_returns(stocks, wts, start_date, end_date=TODAY):
    if len(stocks) > 1:
        assets = yf.download(stocks, start=start_date,
                             end=end_date, progress=False)["Adj Close"]
        assets = assets.filter(stocks)
        ret_data = assets.pct_change()[1:]
        returns = (ret_data * wts).sum(axis=1)
        return returns
    else:
        df = yf.download(stocks, start=start_date,
                         end=end_date, progress=False)["Adj Close"]
        df = pd.DataFrame(df)
        returns = df.pct_change()
        return returns


def get_returns_from_data(data, wts):
    ret_data = data.pct_change()[1:]
    returns = (ret_data * wts).sum(axis=1)
    return returns


def calculate_information_ratio(returns, benchmark_returns, days=252) -> float:
    return_difference = returns - benchmark_returns
    volatility = return_difference.std() * np.sqrt(days)
    information_ratio_result = return_difference.mean() / volatility
    return information_ratio_result


def graph_allocation(my_portfolio):
    fig1, ax1 = plt.subplots()
    ax1.pie(
        my_portfolio.weights,
        labels=my_portfolio.portfolio,
        autopct="%1.1f%%",
        shadow=False,
    )
    # Equal aspect ratio ensures that pie is drawn as a circle.
    ax1.axis("equal")
    plt.title("Portfolio's allocation")
    plt.show()


def sua(my_portfolio, rf=0.0, sigma_value=1, confidence_value=0.95):
    try:
        # we want to get the dataframe with the dates and weights
        rebalance_schedule = my_portfolio.rebalance

        columns = []
        for date in rebalance_schedule.columns:
            date = date[0:10]
            columns.append(date)
        rebalance_schedule.columns = columns

        # then want to make a list of the dates and start with our first date
        dates = [my_portfolio.start_date]

        # then our rebalancing dates into that list
        dates = dates + rebalance_schedule.columns.to_list()

        datess = []
        for date in dates:
            date = date[0:10]
            datess.append(date)
        dates = datess
        # this will hold returns
        returns = pd.Series()

        # then we want to be able to call the dates like tuples
        for i in range(len(dates) - 1):
            # get our weights
            weights = rebalance_schedule[str(dates[i + 1])]

            # then we want to get the returns

            add_returns = get_returns(
                my_portfolio.portfolio,
                weights,
                start_date=dates[i],
                end_date=dates[i + 1],
            )

            # then append those returns
            returns = returns.append(add_returns)

    except AttributeError:
        try:
            returns = get_returns_from_data(
                my_portfolio.data, my_portfolio.weights)
        except AttributeError:
            returns = get_returns(
                my_portfolio.portfolio,
                my_portfolio.weights,
                start_date=my_portfolio.start_date,
                end_date=my_portfolio.end_date,
            )

    creturns = (returns + 1).cumprod()

    # risk manager
    try:
        if list(my_portfolio.risk_manager.keys())[0] == "Stop Loss":

            values = []
            for r in creturns:
                if r <= 1 + my_portfolio.risk_manager["Stop Loss"]:
                    values.append(r)
                else:
                    pass

            try:
                date = creturns[creturns == values[0]].index[0]
                date = str(date.to_pydatetime())
                my_portfolio.end_date = date[0:10]
                returns = returns[: my_portfolio.end_date]

            except Exception as e:
                pass

        if list(my_portfolio.risk_manager.keys())[0] == "Take Profit":

            values = []
            for r in creturns:
                if r >= 1 + my_portfolio.risk_manager["Take Profit"]:
                    values.append(r)
                else:
                    pass

            try:
                date = creturns[creturns == values[0]].index[0]
                date = str(date.to_pydatetime())
                my_portfolio.end_date = date[0:10]
                returns = returns[: my_portfolio.end_date]

            except Exception as e:
                pass

        if list(my_portfolio.risk_manager.keys())[0] == "Max Drawdown":

            drawdown = qs.stats.to_drawdown_series(returns)

            values = []
            for r in drawdown:
                if r <= my_portfolio.risk_manager["Max Drawdown"]:
                    values.append(r)
                else:
                    pass

            try:
                date = drawdown[drawdown == values[0]].index[0]
                date = str(date.to_pydatetime())
                my_portfolio.end_date = date[0:10]
                returns = returns[: my_portfolio.end_date]

            except Exception as e:
                pass

    except Exception as e:
        pass

    print("Start date: " + str(my_portfolio.start_date))
    print("End date: " + str(my_portfolio.end_date))

    benchmark = get_returns(
        my_portfolio.benchmark,
        wts=[1],
        start_date=my_portfolio.start_date,
        end_date=my_portfolio.end_date,
    )
    benchmark = benchmark.dropna()

    CAGR = cagr(returns, period='daily', annualization=None)
    # CAGR = round(CAGR, 2)
    # CAGR = CAGR.tolist()
    CAGR = str(round(CAGR * 100, 2)) + "%"

    CUM = cum_returns(returns, starting_value=0, out=None) * 100
    CUM = CUM.iloc[-1]
    CUM = CUM.tolist()
    CUM = str(round(CUM, 2)) + "%"

    VOL = qs.stats.volatility(returns, annualize=True)
    VOL = VOL.tolist()
    VOL = str(round(VOL * 100, 2)) + " %"

    SR = qs.stats.sharpe(returns, rf=rf)
    SR = np.round(SR, decimals=2)
    SR = str(SR)

    sua.SR = SR

    CR = qs.stats.calmar(returns)
    CR = CR.tolist()
    CR = str(round(CR, 2))

    sua.CR = CR

    STABILITY = stability_of_timeseries(returns)
    STABILITY = round(STABILITY, 2)
    STABILITY = str(STABILITY)

    MD = max_drawdown(returns, out=None)
    MD = str(round(MD * 100, 2)) + " %"

    """OR = omega_ratio(returns, risk_free=0.0, required_return=0.0)
    OR = round(OR,2)
    OR = str(OR)
    print(OR)"""

    SOR = sortino_ratio(returns, required_return=0, period='daily')
    SOR = round(SOR, 2)
    SOR = str(SOR)

    SK = qs.stats.skew(returns)
    SK = round(SK, 2)
    SK = SK.tolist()
    SK = str(SK)

    KU = qs.stats.kurtosis(returns)
    KU = round(KU, 2)
    KU = KU.tolist()
    KU = str(KU)

    TA = tail_ratio(returns)
    TA = round(TA, 2)
    TA = str(TA)

    CSR = qs.stats.common_sense_ratio(returns)
    CSR = round(CSR, 2)
    CSR = CSR.tolist()
    CSR = str(CSR)

    VAR = qs.stats.value_at_risk(
        returns, sigma=sigma_value, confidence=confidence_value
    )
    VAR = np.round(VAR, decimals=2)
    VAR = str(VAR * 100) + " %"

    alpha, beta = alpha_beta(returns, benchmark, risk_free=rf)
    AL = round(alpha, 2)
    BTA = round(beta, 2)

    def condition(x):
        return x > 0

    win = sum(condition(x) for x in returns)
    total = len(returns)
    win_ratio = win / total
    win_ratio = win_ratio * 100
    win_ratio = round(win_ratio, 2)

    IR = calculate_information_ratio(returns, benchmark.iloc[:, 0])
    IR = round(IR, 2)

    data = {
        "": [
            "Annual return",
            "Cumulative return",
            "Annual volatility",
            "Winning day ratio",
            "Sharpe ratio",
            "Calmar ratio",
            "Information ratio",
            "Stability",
            "Max Drawdown",
            "Sortino ratio",
            "Skew",
            "Kurtosis",
            "Tail Ratio",
            "Common sense ratio",
            "Daily value at risk",
            "Alpha",
            "Beta",
        ],
        "Backtest": [
            CAGR,
            CUM,
            VOL,
            f"{win_ratio}%",
            SR,
            CR,
            IR,
            STABILITY,
            MD,
            SOR,
            SK,
            KU,
            TA,
            CSR,
            VAR,
            AL,
            BTA,
        ],
    }

    # Create DataFrame
    df = pd.DataFrame(data)
    df.set_index("", inplace=True)
    df.style.set_properties(
        **{"background-color": "white", "color": "black", "border-color": "black"}
    )
    display(df)

    sua.df = data

    y = []
    for x in returns:
        y.append(x)

    arr = np.array(y)
    # arr
    # returns.index
    my_color = np.where(arr >= 0, "blue", "grey")
    plt.figure(figsize=(30, 8))
    plt.vlines(x=returns.index, ymin=0, ymax=arr, color=my_color, alpha=0.4)
    plt.title("Returns")

    sua.returns = returns
    sua.creturns = creturns
    sua.benchmark = benchmark
    sua.CAGR = CAGR
    sua.CUM = CUM
    sua.VOL = VOL
    sua.SR = SR
    sua.win_ratio = win_ratio
    sua.CR = CR
    sua.IR = IR
    sua.STABILITY = STABILITY
    sua.MD = MD
    sua.SOR = SOR
    sua.SK = SK
    sua.KU = KU
    sua.TA = TA
    sua.CSR = CSR
    sua.VAR = VAR
    sua.AL = AL
    sua.BTA = BTA

    try:
        sua.orderbook = make_rebalance.output
    except Exception as e:
        OrderBook = pd.DataFrame(
            {
                "Assets": my_portfolio.portfolio,
                "Allocation": my_portfolio.weights,
            }
        )

        sua.orderbook = OrderBook.T

    wts = copy.deepcopy(my_portfolio.weights)
    indices = [i for i, x in enumerate(wts) if x == 0.0]

    while 0.0 in wts:
        wts.remove(0.0)

    for i in sorted(indices, reverse=True):
        del my_portfolio.portfolio[i]

    return (
        qs.plots.returns(returns, benchmark, cumulative=True),
        qs.plots.yearly_returns(returns, benchmark),
        qs.plots.monthly_heatmap(returns),
        qs.plots.drawdown(returns),
        qs.plots.drawdowns_periods(returns),
        qs.plots.rolling_volatility(returns),
        qs.plots.rolling_sharpe(returns),
        qs.plots.rolling_beta(returns, benchmark),
        graph_opt(my_portfolio.portfolio, wts, pie_size=7, font_size=14),
    )


def flatten(subject) -> list:
    muster = []
    for item in subject:
        if isinstance(item, (list, tuple, set)):
            muster.extend(flatten(item))
        else:
            muster.append(item)
    return muster


def graph_opt(my_portfolio, my_weights, pie_size, font_size):
    fig1, ax1 = plt.subplots()
    fig1.set_size_inches(pie_size, pie_size)
    cs = [
        "#ff9999",
        "#66b3ff",
        "#99ff99",
        "#ffcc99",
        "#f6c9ff",
        "#a6fff6",
        "#fffeb8",
        "#ffe1d4",
        "#cccdff",
        "#fad6ff",
    ]
    ax1.pie(my_weights, labels=my_portfolio,
            autopct="%1.1f%%", shadow=False, colors=cs)
    # Equal aspect ratio ensures that pie is drawn as a circle.
    ax1.axis("equal")
    plt.rcParams["font.size"] = font_size
    plt.show()


def equal_weighting(my_portfolio) -> list:
    return [1.0 / len(my_portfolio.portfolio)] * len(my_portfolio.portfolio)


def efficient_frontier(my_portfolio, perf=True) -> list:
    # changed to take in desired timeline, the problem is that it would use all historical data
    ohlc = yf.download(
        my_portfolio.portfolio,
        start=my_portfolio.start_date,
        end=my_portfolio.end_date,
        progress=False,
    )
    prices = ohlc["Adj Close"].dropna(how="all")
    df = prices.filter(my_portfolio.portfolio)

    # sometimes we will pick a date range where company isn't public we can't set price to 0 so it has to go to 1
    df = df.fillna(1)

    mu = expected_returns.mean_historical_return(df)
    S = risk_models.sample_cov(df)

    # optimize for max sharpe ratio
    ef = EfficientFrontier(mu, S)

    if my_portfolio.min_weights is not None:
        ef.add_constraint(lambda x: x >= my_portfolio.min_weights)
    if my_portfolio.max_weights is not None:
        ef.add_constraint(lambda x: x <= my_portfolio.max_weights)
    weights = ef.max_sharpe()
    cleaned_weights = ef.clean_weights()
    wts = cleaned_weights.items()

    result = []
    for val in wts:
        a, b = map(list, zip(*[val]))
        result.append(b)

    if perf is True:
        pred = ef.portfolio_performance(verbose=True)

    return flatten(result)


def hrp(my_portfolio, perf=True) -> list:
    # changed to take in desired timeline, the problem is that it would use all historical data

    ohlc = yf.download(
        my_portfolio.portfolio,
        start=my_portfolio.start_date,
        end=my_portfolio.end_date,
        progress=False,
    )
    prices = ohlc["Adj Close"].dropna(how="all")
    prices = prices.filter(my_portfolio.portfolio)

    # sometimes we will pick a date range where company isn't public we can't set price to 0 so it has to go to 1
    prices = prices.fillna(1)

    rets = expected_returns.returns_from_prices(prices)
    hrp = HRPOpt(rets)
    hrp.optimize()
    weights = hrp.clean_weights()

    wts = weights.items()

    result = []
    for val in wts:
        a, b = map(list, zip(*[val]))
        result.append(b)

    if perf is True:
        hrp.portfolio_performance(verbose=True)

    return flatten(result)


def mean_var(my_portfolio, vol_max=0.15, perf=True) -> list:
    # changed to take in desired timeline, the problem is that it would use all historical data

    ohlc = yf.download(
        my_portfolio.portfolio,
        start=my_portfolio.start_date,
        end=my_portfolio.end_date,
        progress=False,
    )
    prices = ohlc["Adj Close"].dropna(how="all")
    prices = prices.filter(my_portfolio.portfolio)

    # sometimes we will pick a date range where company isn't public we can't set price to 0 so it has to go to 1
    prices = prices.fillna(1)

    mu = expected_returns.capm_return(prices)
    S = risk_models.CovarianceShrinkage(prices).ledoit_wolf()

    ef = EfficientFrontier(mu, S)
    ef.add_objective(objective_functions.L2_reg,
                     gamma=my_portfolio.diversification)
    if my_portfolio.min_weights is not None:
        ef.add_constraint(lambda x: x >= my_portfolio.min_weights)
    if my_portfolio.max_weights is not None:
        ef.add_constraint(lambda x: x <= my_portfolio.max_weights)
    ef.efficient_risk(vol_max)
    weights = ef.clean_weights()

    wts = weights.items()

    result = []
    for val in wts:
        a, b = map(list, zip(*[val]))
        result.append(b)

    if perf is True:
        ef.portfolio_performance(verbose=True)

    return flatten(result)


def min_var(my_portfolio, perf=True) -> list:
    ohlc = yf.download(
        my_portfolio.portfolio,
        start=my_portfolio.start_date,
        end=my_portfolio.end_date,
        progress=False,
    )
    prices = ohlc["Adj Close"].dropna(how="all")
    prices = prices.filter(my_portfolio.portfolio)

    mu = expected_returns.capm_return(prices)
    S = risk_models.CovarianceShrinkage(prices).ledoit_wolf()

    ef = EfficientFrontier(mu, S)
    ef.add_objective(objective_functions.L2_reg,
                     gamma=my_portfolio.diversification)
    if my_portfolio.min_weights is not None:
        ef.add_constraint(lambda x: x >= my_portfolio.min_weights)
    if my_portfolio.max_weights is not None:
        ef.add_constraint(lambda x: x <= my_portfolio.max_weights)
    ef.min_volatility()
    weights = ef.clean_weights()

    wts = weights.items()

    result = []
    for val in wts:
        a, b = map(list, zip(*[val]))
        result.append(b)

    if perf is True:
        ef.portfolio_performance(verbose=True)

    return flatten(result)


def optimize_portfolio(my_portfolio, vol_max=25, pie_size=5, font_size=14):
    returns1 = get_returns(
        my_portfolio.portfolio,
        equal_weighting(my_portfolio),
        start_date=my_portfolio.start_date,
        end_date=my_portfolio.end_date,
    )
    creturns1 = (returns1 + 1).cumprod()

    port = copy.deepcopy(my_portfolio.portfolio)

    wts = [1.0 / len(my_portfolio.portfolio)] * len(my_portfolio.portfolio)

    optimizers = {
        "EF": efficient_frontier,
        "MEANVAR": mean_var,
        "HRP": hrp,
        "MINVAR": min_var,
    }

    if my_portfolio.optimizer in optimizers.keys():
        if my_portfolio.optimizer == "MEANVAR":
            wts = optimizers.get(my_portfolio.optimizer)(
                my_portfolio, my_portfolio.max_vol)
        else:
            wts = optimizers.get(my_portfolio.optimizer)(my_portfolio)
    else:
        opt = my_portfolio.optimizer
        my_portfolio.weights = opt()

    print(wts)
    print("\n")

    indices = [i for i, x in enumerate(wts) if x == 0.0]

    while 0.0 in wts:
        wts.remove(0.0)

    for i in sorted(indices, reverse=True):
        del port[i]

    graph_opt(port, wts, pie_size, font_size)

    print("\n")

    returns2 = get_returns(
        port, wts, start_date=my_portfolio.start_date, end_date=my_portfolio.end_date
    )
    creturns2 = (returns2 + 1).cumprod()

    plt.rcParams["font.size"] = 13
    plt.figure(figsize=(30, 10))
    plt.xlabel("Portfolio vs Benchmark")

    ax1 = creturns1.plot(color="blue", label="Without optimization")
    ax2 = creturns2.plot(color="red", label="With optimization")

    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()

    plt.legend(l1 + l2, loc=2)
    plt.show()


def check_schedule(rebalance) -> bool:
    valid_schedule = False
    if rebalance.lower() in rebalance_periods.keys():
        valid_schedule = True
    return valid_schedule


def valid_range(start_date, end_date, rebalance) -> tuple:
    # make the start date to a datetime
    start_date = dt.datetime.strptime(start_date, "%Y-%m-%d")

    # have to make end date a datetime because strptime is not supported for date
    end_date = dt.datetime(end_date.year, end_date.month, end_date.day)

    # gets the number of days
    days = (end_date - start_date).days

    # checking that date range covers rebalance period
    if rebalance in rebalance_periods.keys() and days <= (int(rebalance_periods[rebalance])):
        raise KeyError("Date Range does not encompass rebalancing interval")

    # we will needs these dates later on so we'll return them back
    return start_date, end_date


def get_date_range(start_date, end_date, rebalance) -> list:
    # this will keep track of the rebalancing dates and we want to start on the first date
    rebalance_dates = [start_date]
    input_date = start_date

    if rebalance in rebalance_periods.keys():
        # run for an arbitrarily large number we'll resolve this by breaking when we break the equality
        for i in range(1000):
            # increment the date based on the selected period
            input_date = input_date + \
                dt.timedelta(days=rebalance_periods.get(rebalance))
            if input_date <= end_date:
                # append the new date if it is earlier or equal to the final date
                rebalance_dates.append(input_date)
            else:
                # break when the next rebalance date is later than our end date
                break

    # then we want to return those dates
    return rebalance_dates


def make_rebalance(
    start_date,
    end_date,
    optimize,
    portfolio_input,
    rebalance,
    allocation,
    vol_max,
    div,
    min,
    max,
) -> pd.DataFrame:
    sdate = str(start_date)[:10]
    if rebalance[0] != sdate:

        # makes sure that the value passed through for rebalancing is a valid one
        valid_schedule = check_schedule(rebalance)

        if valid_schedule is False:
            raise KeyError("Not an accepted rebalancing schedule")

    # this checks to make sure that the date range given works for the rebalancing
    start_date, end_date = valid_range(start_date, end_date, rebalance)

    # this function will get us the specific dates
    if rebalance[0] != sdate:
        dates = get_date_range(start_date, end_date, rebalance)
    else:
        dates = rebalance

    # we are going to make columns with the end date and the weights
    columns = ["end_date"] + portfolio_input

    # then make a dataframe with the index being the tickers
    output_df = pd.DataFrame(index=portfolio_input)

    for i in range(len(dates) - 1):

        try:
            portfolio = Engine(
                start_date=dates[0],
                end_date=dates[i + 1],
                portfolio=portfolio_input,
                weights=allocation,
                optimizer="{}".format(optimize),
                max_vol=vol_max,
                diversification=div,
                min_weights=min,
                max_weights=max,
            )

        except TypeError:
            portfolio = Engine(
                start_date=dates[0],
                end_date=dates[i + 1],
                portfolio=portfolio_input,
                weights=allocation,
                optimizer=optimize,
                max_vol=vol_max,
                diversification=div,
                min_weights=min,
                max_weights=max,
            )

        output_df["{}".format(dates[i + 1])] = portfolio.weights

    # we have to run it one more time to get what the optimization is for up to today's date
    try:
        portfolio = Engine(
            start_date=dates[0],
            portfolio=portfolio_input,
            weights=allocation,
            optimizer="{}".format(optimize),
            max_vol=vol_max,
            diversification=div,
            min_weights=min,
            max_weights=max,
        )

    except TypeError:
        portfolio = Engine(
            start_date=dates[0],
            portfolio=portfolio_input,
            weights=allocation,
            optimizer=optimize,
            max_vol=vol_max,
            diversification=div,
            min_weights=min,
            max_weights=max,
        )

    output_df["{}".format(TODAY)] = portfolio.weights

    make_rebalance.output = output_df
    return output_df


def get_report(my_portfolio, rf=0.0, sigma_value=1, confidence_value=0.95, filename: str = "report.pdf"):
    try:
        # we want to get the dataframe with the dates and weights
        rebalance_schedule = my_portfolio.rebalance

        columns = []
        for date in rebalance_schedule.columns:
            date = date[0:10]
            columns.append(date)
        rebalance_schedule.columns = columns

        # then want to make a list of the dates and start with our first date
        dates = [my_portfolio.start_date]

        # then our rebalancing dates into that list
        dates = dates + rebalance_schedule.columns.to_list()

        datess = []
        for date in dates:
            date = date[0:10]
            datess.append(date)
        dates = datess
        # this will hold returns
        returns = pd.Series()

        # then we want to be able to call the dates like tuples
        for i in range(len(dates) - 1):
            # get our weights
            weights = rebalance_schedule[str(dates[i + 1])]

            # then we want to get the returns

            add_returns = get_returns(
                my_portfolio.portfolio,
                weights,
                start_date=dates[i],
                end_date=dates[i + 1],
            )

            # then append those returns
            returns = returns.append(add_returns)

    except AttributeError:
        try:
            returns = get_returns_from_data(
                my_portfolio.data, my_portfolio.weights)
        except AttributeError:
            returns = get_returns(
                my_portfolio.portfolio,
                my_portfolio.weights,
                start_date=my_portfolio.start_date,
                end_date=my_portfolio.end_date,
            )

    creturns = (returns + 1).cumprod()

    # risk manager
    try:
        if list(my_portfolio.risk_manager.keys())[0] == "Stop Loss":

            values = []
            for r in creturns:
                if r <= 1 + my_portfolio.risk_manager["Stop Loss"]:
                    values.append(r)
                else:
                    pass

            try:
                date = creturns[creturns == values[0]].index[0]
                date = str(date.to_pydatetime())
                my_portfolio.end_date = date[0:10]
                returns = returns[: my_portfolio.end_date]

            except Exception as e:
                pass

        if list(my_portfolio.risk_manager.keys())[0] == "Take Profit":

            values = []
            for r in creturns:
                if r >= 1 + my_portfolio.risk_manager["Take Profit"]:
                    values.append(r)
                else:
                    pass

            try:
                date = creturns[creturns == values[0]].index[0]
                date = str(date.to_pydatetime())
                my_portfolio.end_date = date[0:10]
                returns = returns[: my_portfolio.end_date]

            except Exception as e:
                pass

        if list(my_portfolio.risk_manager.keys())[0] == "Max Drawdown":

            drawdown = qs.stats.to_drawdown_series(returns)

            values = []
            for r in drawdown:
                if r <= my_portfolio.risk_manager["Max Drawdown"]:
                    values.append(r)
                else:
                    pass

            try:
                date = drawdown[drawdown == values[0]].index[0]
                date = str(date.to_pydatetime())
                my_portfolio.end_date = date[0:10]
                returns = returns[: my_portfolio.end_date]

            except Exception as e:
                pass

    except Exception as e:
        pass

    fig1, ax1 = plt.subplots()
    fig1.set_size_inches(5, 5)

    # defining colors for the allocation pie
    cs = [
        "#ff9999",
        "#66b3ff",
        "#99ff99",
        "#ffcc99",
        "#f6c9ff",
        "#a6fff6",
        "#fffeb8",
        "#ffe1d4",
        "#cccdff",
        "#fad6ff",
    ]

    wts = copy.deepcopy(my_portfolio.weights)
    port = copy.deepcopy(my_portfolio.portfolio)
    indices = [i for i, x in enumerate(wts) if x == 0.0]

    while 0.0 in wts:
        wts.remove(0.0)

    for i in sorted(indices, reverse=True):
        del port[i]

    ax1.pie(wts, labels=port, autopct="%1.1f%%", shadow=False, colors=cs)
    # Equal aspect ratio ensures that pie is drawn as a circle.
    ax1.axis("equal")
    plt.rcParams["font.size"] = 12
    plt.close(fig1)
    fig1.savefig("allocation.png")

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("arial", "B", 14)
    pdf.cell(20, 15, f"Report", ln=1)
    pdf.set_font("arial", size=11)
    pdf.cell(20, 7, f"Start date: " + str(my_portfolio.start_date), ln=1)
    pdf.cell(20, 7, f"End date: " + str(my_portfolio.end_date), ln=1)

    benchmark = get_returns(
        my_portfolio.benchmark,
        wts=[1],
        start_date=my_portfolio.start_date,
        end_date=my_portfolio.end_date,
    )

    CAGR = cagr(returns, period='daily', annualization=None)
    # CAGR = round(CAGR, 2)
    # CAGR = CAGR.tolist()
    CAGR = str(round(CAGR * 100, 2)) + "%"

    CUM = cum_returns(returns, starting_value=0, out=None) * 100
    CUM = CUM.iloc[-1]
    CUM = CUM.tolist()
    CUM = str(round(CUM, 2)) + "%"

    VOL = qs.stats.volatility(returns, annualize=True)
    VOL = VOL.tolist()
    VOL = str(round(VOL * 100, 2)) + " %"

    SR = qs.stats.sharpe(returns, rf=rf)
    SR = np.round(SR, decimals=2)
    SR = str(SR)

    sua.SR = SR

    CR = qs.stats.calmar(returns)
    CR = CR.tolist()
    CR = str(round(CR, 2))

    sua.CR = CR

    STABILITY = stability_of_timeseries(returns)
    STABILITY = round(STABILITY, 2)
    STABILITY = str(STABILITY)

    MD = max_drawdown(returns, out=None)
    MD = str(round(MD * 100, 2)) + " %"

    """OR = omega_ratio(returns, risk_free=0.0, required_return=0.0)
    OR = round(OR,2)
    OR = str(OR)
    print(OR)"""

    SOR = sortino_ratio(returns, required_return=0, period='daily')
    SOR = round(SOR, 2)
    SOR = str(SOR)

    SK = qs.stats.skew(returns)
    SK = round(SK, 2)
    SK = SK.tolist()
    SK = str(SK)

    KU = qs.stats.kurtosis(returns)
    KU = round(KU, 2)
    KU = KU.tolist()
    KU = str(KU)

    TA = tail_ratio(returns)
    TA = round(TA, 2)
    TA = str(TA)

    CSR = qs.stats.common_sense_ratio(returns)
    CSR = round(CSR, 2)
    CSR = CSR.tolist()
    CSR = str(CSR)

    VAR = qs.stats.value_at_risk(
        returns, sigma=sigma_value, confidence=confidence_value
    )
    VAR = np.round(VAR, decimals=2)
    VAR = str(VAR * 100) + " %"

    alpha, beta = alpha_beta(returns, benchmark, risk_free=rf)
    AL = round(alpha, 2)
    BTA = round(beta, 2)

    def condition(x):
        return x > 0

    win = sum(condition(x) for x in returns)
    total = len(returns)
    win_ratio = win / total
    win_ratio = win_ratio * 100
    win_ratio = round(win_ratio, 2)

    IR = calculate_information_ratio(returns, benchmark.iloc[:, 0])
    IR = round(IR, 2)

    data = {
        "": [
            "Annual return",
            "Cumulative return",
            "Annual volatility",
            "Winning day ratio",
            "Sharpe ratio",
            "Calmar ratio",
            "Information ratio",
            "Stability",
            "Max Drawdown",
            "Sortino ratio",
            "Skew",
            "Kurtosis",
            "Tail Ratio",
            "Common sense ratio",
            "Daily value at risk",
            "Alpha",
            "Beta",
        ],
        "Backtest": [
            CAGR,
            CUM,
            VOL,
            f"{win_ratio}%",
            SR,
            CR,
            IR,
            STABILITY,
            MD,
            SOR,
            SK,
            KU,
            TA,
            CSR,
            VAR,
            AL,
            BTA,
        ],
    }

    # Create DataFrame
    df = pd.DataFrame(data)
    df.set_index("", inplace=True)
    df.style.set_properties(
        **{"background-color": "white", "color": "black", "border-color": "black"}
    )

    sua.df = data

    y = []
    for x in returns:
        y.append(x)

    arr = np.array(y)
    # arr
    # returns.index
    my_color = np.where(arr >= 0, "blue", "grey")
    ret = plt.figure(figsize=(30, 8))
    plt.vlines(x=returns.index, ymin=0, ymax=arr, color=my_color, alpha=0.4)
    plt.title("Returns")
    plt.close(ret)
    ret.savefig("ret.png")

    pdf.cell(20, 7, f"", ln=1)
    pdf.cell(20, 7, f"Annual return: " + str(CAGR), ln=1)
    pdf.cell(20, 7, f"Cumulative return: " + str(CUM), ln=1)
    pdf.cell(20, 7, f"Annual volatility: " + str(VOL), ln=1)
    pdf.cell(20, 7, f"Winning day ratio: " + str(win_ratio), ln=1)
    pdf.cell(20, 7, f"Sharpe ratio: " + str(SR), ln=1)
    pdf.cell(20, 7, f"Calmar ratio: " + str(CR), ln=1)
    pdf.cell(20, 7, f"Information ratio: " + str(IR), ln=1)
    pdf.cell(20, 7, f"Stability: " + str(STABILITY), ln=1)
    pdf.cell(20, 7, f"Max drawdown: " + str(MD), ln=1)
    pdf.cell(20, 7, f"Sortino ratio: " + str(SOR), ln=1)
    pdf.cell(20, 7, f"Skew: " + str(SK), ln=1)
    pdf.cell(20, 7, f"Kurtosis: " + str(KU), ln=1)
    pdf.cell(20, 7, f"Tail ratio: " + str(TA), ln=1)
    pdf.cell(20, 7, f"Common sense ratio: " + str(CSR), ln=1)
    pdf.cell(20, 7, f"Daily value at risk: " + str(VAR), ln=1)
    pdf.cell(20, 7, f"Alpha: " + str(AL), ln=1)
    pdf.cell(20, 7, f"Beta: " + str(BTA), ln=1)

    qs.plots.returns(
        returns, benchmark, cumulative=True, savefig="retbench.png", show=False
    )
    qs.plots.yearly_returns(
        returns, benchmark, savefig="y_returns.png", show=False),
    qs.plots.monthly_heatmap(returns, savefig="heatmap.png", show=False)
    qs.plots.drawdown(returns, savefig="drawdown.png", show=False)
    qs.plots.drawdowns_periods(returns, savefig="d_periods.png", show=False)
    qs.plots.rolling_volatility(returns, savefig="rvol.png", show=False)
    qs.plots.rolling_sharpe(returns, savefig="rsharpe.png", show=False)
    qs.plots.rolling_beta(returns, benchmark, savefig="rbeta.png", show=False)

    pdf.image("ret.png", x=-20, y=None, w=250, h=80, type="", link="")
    pdf.cell(20, 7, f"", ln=1)
    pdf.image("y_returns.png", x=-20, y=None, w=200, h=100, type="", link="")
    pdf.cell(20, 7, f"", ln=1)
    pdf.image("retbench.png", x=None, y=None, w=200, h=100, type="", link="")
    pdf.cell(20, 7, f"", ln=1)
    pdf.image("heatmap.png", x=None, y=None, w=200, h=80, type="", link="")
    pdf.cell(20, 7, f"", ln=1)
    pdf.image("drawdown.png", x=None, y=None, w=200, h=80, type="", link="")
    pdf.cell(20, 7, f"", ln=1)
    pdf.image("d_periods.png", x=None, y=None, w=200, h=80, type="", link="")
    pdf.cell(20, 7, f"", ln=1)
    pdf.image("rvol.png", x=None, y=None, w=190, h=80, type="", link="")
    pdf.cell(20, 7, f"", ln=1)
    pdf.image("rsharpe.png", x=None, y=None, w=190, h=80, type="", link="")
    pdf.cell(20, 7, f"", ln=1)
    pdf.image("rbeta.png", x=None, y=None, w=190, h=80, type="", link="")

    pdf.output(dest="F", name=filename)


def geronimo(portfolio, start_date, weights=None, prediction_days=None, based_on='Adj Close'):
    print("Collecting datas...")
    # define weights
    if weights == None:
        weights = [1.0 / len(portfolio)] * len(portfolio)

    # define today
    today = dt.datetime.today().strftime('%Y-%m-%d')

    # clean output from warning
    logger = logging.getLogger()
    warnings.simplefilter(action='ignore', category=FutureWarning)
    filterwarnings('ignore')

    logging.disable(logging.INFO)

    mape_df = pd.DataFrame()
    mape_df = mape_df.append(
        {'Exponential smoothing': 0, 'Prophet': 0, 'Auto-ARIMA': 0, 'Theta(2)': 0, 'ARIMA': 0, 'FFT': 0, 'FourTheta': 0,
         'NaiveDrift': 0, 'NaiveMean': 0, 'NaiveSeasonal': 0},
        ignore_index=True)

    final_df = pd.DataFrame()
    final_df = final_df.append(
        {'Exponential smoothing': 0, 'Prophet': 0, 'Auto-ARIMA': 0, 'Theta(2)': 0, 'ARIMA': 0, 'FFT': 0, 'FourTheta': 0,
         'NaiveDrift': 0, 'NaiveMean': 0, 'NaiveSeasonal': 0},
        ignore_index=True)

    for asset in portfolio:

        result = pd.DataFrame()
        df = yf.download(asset, start=start_date, end=today,
                         progress=False)["Adj Close"]
        df = pd.DataFrame(df)
        df.reset_index(level=0, inplace=True)

        if prediction_days == None:
            x = 1
            while x / (len(df) + x) < 0.3:
                x += 1
                prediction_days = x

        def eval_model(model):
            model.fit(train)
            forecast = model.predict(len(val))
            result[model] = [mape(val, forecast)]

        prediction = pd.DataFrame()

        def predict(model):
            model.fit(train)
            forecast = model.predict(len(val))
            pred = model.predict(prediction_days)
            b = [str(pred[-1][0][0])][0]
            b = b.split("array([[[")
            c = b[1].split("]]])")
            d = c[0][: -3]
            b = float(d)
            prediction[model] = [
                str(round(((b - start_value) / start_value) * 100, 3)) + ' %']

        series = TimeSeries.from_dataframe(df, 'Date', based_on, freq='D')
        series = fill_missing_values(series)

        train_index = round(len(df.index) * 0.7)
        train_date = df.loc[[train_index]]['Date'].values
        date = str(train_date[0])[:10]
        date = date.replace('-', '')
        timestamp = date + '000000'
        train, val = series.split_before(pd.Timestamp(timestamp))

        print("Evaluating the models for " + str(asset) + "...")

        eval_model(ExponentialSmoothing())
        eval_model(Prophet())
        eval_model(AutoARIMA())
        eval_model(Theta())
        eval_model(ARIMA())
        eval_model(FFT())
        eval_model(FourTheta())
        eval_model(NaiveDrift())
        eval_model(NaiveMean())
        eval_model(NaiveSeasonal())

        print("Models evaluated!")

        result.columns = ['Exponential smoothing', 'Prophet', 'Auto-ARIMA', 'Theta(2)', 'ARIMA', 'FFT', 'FourTheta',
                          'NaiveDrift', 'NaiveMean', 'NaiveSeasonal']
        result.index = [asset]
        mape_df = pd.concat([result, mape_df])
        start_pred = str(df["Date"].iloc[-1])[:10]
        start_value = df[based_on].iloc[-1]
        start_pred = start_pred.replace('-', '')
        timestamp = start_pred + '000000'
        train, val = series.split_before(pd.Timestamp(timestamp))

        print("Making the predictions for " + str(asset) + "...")
        predict(ExponentialSmoothing())
        predict(Prophet())
        predict(AutoARIMA())
        predict(Theta())
        predict(ARIMA())
        predict(FFT())
        predict(FourTheta())
        predict(NaiveDrift())
        predict(NaiveMean())
        predict(NaiveSeasonal())
        print("Predictions generated!")

        prediction.columns = ['Exponential smoothing', 'Prophet', 'Auto-ARIMA', 'Theta(2)', 'ARIMA', 'FFT', 'FourTheta',
                              'NaiveDrift', 'NaiveMean', 'NaiveSeasonal']
        prediction.index = [asset]
        final_df = pd.concat([prediction, final_df])

    print("\n")
    print("Assets MAPE (accuracy score)")
    with pd.option_context('display.max_rows', None, 'display.max_columns', None) and pd.option_context(
            'expand_frame_repr', False):
        print(mape_df.iloc[:-1, :])
    mape_df = pd.DataFrame(mape_df.iloc[:-1, :])
    print("\n")
    print("Assets returns prediction for the next " +
          str(prediction_days) + " days")
    with pd.option_context('display.max_rows', None, 'display.max_columns', None) and pd.option_context(
            'expand_frame_repr', False):
        print(final_df.iloc[:-1, :])
    final_df = pd.DataFrame(final_df.iloc[:-1, :])

    portfolio_pred = pd.DataFrame()

    for column in final_df.columns:
        rets = []
        for index in final_df.index:
            place = portfolio.index(index)
            returns = float(final_df[column][index][:-1])
            wts = weights[portfolio.index(index)]
            ret = (returns * wts)
            rets.append(ret)
        portfolio_pred[column] = rets
        portfolio_pred[column] = portfolio_pred[column].sum()

    print("\n")
    print("Portfolio returns prediction for the next " +
          str(prediction_days) + " days")
    print(portfolio_pred.iloc[0])

    logger.disabled = False
