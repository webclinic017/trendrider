from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
import pandas as pd
import os

import threading
import time

class IBapi(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self,self)

    def tickPrice(self, reqId, tickType, price, attrib):
        if tickType==2 and reqId==1:
            print('The current ask price is:', price)

    def historicalData(self, reqId, bar):
        # print(f'Time: {bar.date} Close: {bar.close}')
        print("Bar:",bar)

def run_loop():
    ib.run()

def stock_update(id,stock):
#Create contract object
    contract = Contract()
    contract.symbol = stock
    contract.secType = 'STK'
    contract.exchange = 'SMART'
    contract.currency = 'USD'

#Request Market Data
# app.reqMktData(1, apple_contract, '', False, False, [])
    ib.reqHistoricalData(id,contract,'','1 D','10 secs','TRADES',0,2,False,[])

ib = IBapi()
ib.connect('127.0.0.1',7497,123)

api_thread = threading.Thread(target=run_loop, daemon=True)
api_thread.start()

time.sleep(1)

script_path = os.path.abspath(__file__)
script_dir = os.path.dirname(script_path)
stocks = pd.read_csv(os.path.join(script_dir,'stock.csv'),header=0)

for i in range(len(stocks.index)):
# for i in range(2):
    if isinstance(stocks.iloc[i]['Symbol'], str):
        ticker = stocks.iloc[i]['Symbol'].upper()
        print("Ticker:",ticker)
        stock_update(i,ticker)
    time.sleep(1)

time.sleep(10) #Sleep interval to allow time for incoming price data
ib.disconnect()
