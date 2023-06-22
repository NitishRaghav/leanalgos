from AlgorithmImports import *
import System

from indicators import *
from indicators.clippedEigenIndicator import ClippedEigenIndicator
from indicators.constrainedIndicator import ConstrainedIndicator
from indicators.cvClippingIndicator import CVClippingIndicator
from indicators.cvIndicator import CVIndicator
from indicators.oracleIndicator import OracleIndicator

class MarkowitzHistoricalAlphaModel(AlphaModel):
    '''Uses Historical returns to create insights.'''

    def __init__(self, *args, **kwargs):
        '''Initializes a new default instance of the HistoricalReturnsAlphaModel class.
        Args:
            lookback(int): Historical return lookback period
            resolution: The resolution of historical data'''
        self.lookback = kwargs['lookback'] if 'lookback' in kwargs else 1
        self.resolution = kwargs['resolution'] if 'resolution' in kwargs else Resolution.Daily
        self.predictionInterval = Time.Multiply(Extensions.ToTimeSpan(self.resolution), self.lookback)
        self.symbolDataBySymbol = {}
        self.insightCollection = InsightCollection()
        self.indicator = kwargs['indicator'] if 'indicator' in kwargs else IndicatorPref.cvClipping

    def Update(self, algorithm, data):
        '''Updates this alpha model with the latest data from the algorithm.
        This is called each time the algorithm receives data for subscribed securities
        Args:
            algorithm: The algorithm instance
            data: The new data available
        Returns:
            The new insights generated'''
        insights = []

        for symbol, symbolData in self.symbolDataBySymbol.items():
            if symbolData.CanEmit:

                direction = InsightDirection.Flat
                magnitude = symbolData.Return
                if magnitude > 0: direction = InsightDirection.Up
                if magnitude < 0: direction = InsightDirection.Down
                
                if direction == InsightDirection.Flat:
                    self.CancelInsights(algorithm, symbol)
                    continue

                insights.append(Insight.Price(symbol, self.predictionInterval, direction, magnitude, None))

        self.insightCollection.AddRange(insights)
        return insights

    def OnSecuritiesChanged(self, algorithm, changes):
        '''Event fired each time the we add/remove securities from the data feed
        Args:
            algorithm: The algorithm instance that experienced the change in securities
            changes: The security additions and removals from the algorithm'''

        # clean up data for removed securities
        for removed in changes.RemovedSecurities:
            symbolData = self.symbolDataBySymbol.pop(removed.Symbol, None)
            if symbolData is not None:
                symbolData.RemoveConsolidators(algorithm)
            self.CancelInsights(algorithm, removed.Symbol)

        # initialize data for added securities
        symbols = [ x.Symbol for x in changes.AddedSecurities ]
        history = algorithm.History(symbols, self.lookback, self.resolution)
        if history.empty: return

        tickers = history.index.levels[0]
        for ticker in tickers:
            symbol = SymbolCache.GetSymbol(ticker)

            if symbol not in self.symbolDataBySymbol:
                symbolData = SymbolData(symbol, self.lookback, self.indicator)
                self.symbolDataBySymbol[symbol] = symbolData
                symbolData.RegisterIndicators(algorithm, self.resolution)
                symbolData.WarmUpIndicators(history.loc[ticker])

    def CancelInsights(self, algorithm, symbol):
        if not self.insightCollection.ContainsKey(symbol):
            return
        insights = self.insightCollection[symbol]
        algorithm.Insights.Cancel(insights)
        self.insightCollection.Clear([ symbol ]);


class IndicatorPref(System.Enum):
    """Specifies the indicator to use"""

    Constrained = 0

    ClippedEigen = 1

    Oracle = 2

    cv = 3

    cvClipping = 4

class SymbolData:
    '''Contains data specific to a symbol required by this model'''
    def __init__(self, symbol, lookback, indicator: IndicatorPref):
        self.Symbol = symbol
        # match indicator:
        #     case IndicatorPref.Constrained:
        #         self.indicator = ConstrainedIndicator("Constrained", lookback)
        #     case IndicatorPref.ClippedEigen:
        #         self.indicator = ClippedEigenIndicator("ClippedEigen", lookback)
        #     case IndicatorPref.Oracle:
        #         self.indicator = OracleIndicator("Oracle", lookback)
        #     case IndicatorPref.cv:
        #         self.indicator = CVIndicator("CV", lookback)
        #     case IndicatorPref.cvClipping:
        #         self.indicator = CVClippingIndicator("Cv Clipping", lookback)
        #     case default:
        self.indicator = CVClippingIndicator("Cv Clipping", lookback)
        self.Consolidator = None
        self.previous = 0

    def RegisterIndicators(self, algorithm, resolution):
        self.Consolidator = algorithm.ResolveConsolidator(self.Symbol, resolution)
        algorithm.RegisterIndicator(self.Symbol, self.indicator, self.Consolidator)

    def RemoveConsolidators(self, algorithm):
        if self.Consolidator is not None:
            algorithm.SubscriptionManager.RemoveConsolidator(self.Symbol, self.Consolidator)

    def WarmUpIndicators(self, history):
        for tuple in history.itertuples():
            self.indicator.Update(tuple.Index, tuple.close)

    @property
    def Return(self):
        return float(self.indicator.Current.Value)

    @property
    def CanEmit(self):
        if self.previous == self.indicator.Samples:
            return False

        self.previous = self.indicator.Samples
        return self.indicator.IsReady

    def __str__(self, **kwargs):
        return '{}: {:.2%}'.format(self.indicator.Name, (1 + self.Return)**252 - 1)