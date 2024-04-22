from re import template
from typing import Union,Annotated

from fastapi import FastAPI, Response, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pydantic import BaseModel

import sqlite3
import math

from ibapi.client import EClient, ScannerSubscription
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order
import pandas as pd
import os

import threading
import time

from contextlib import asynccontextmanager

class IBapi(EWrapper, EClient):
    def __init__(self):
        print("Initing myself")
        EClient.__init__(self,self)

    def tickSize(self, reqId, tickType, size):
        # print("In tickprice")
        # print('Id:',reqId,' Size:', size,' TickType:',tickType)
        con = sqlite3.connect(os.path.join(script_dir,'trendrider.db'))
        cursor = con.cursor()
        if tickType==8:
            cursor.execute("UPDATE positions set volume=?,timestamp=datetime('now','localtime') where id=?",(size,reqId))
            cursor.execute("INSERT INTO prices (ticker_id,timestamp,volume) values (?,datetime('now','localtime'),?)",(reqId,size))
        con.commit()
        con.close()

    def tickPrice(self, reqId, tickType, price, attrib):
        # print("In tickprice")
        # print('Id:',reqId,' Price:', price,' TickType:',tickType,' attrib:',attrib)
        con = sqlite3.connect(os.path.join(script_dir,'trendrider.db'))
        cursor = con.cursor()
        if tickType==4:
            cursor.execute("UPDATE positions set prev_last_price=last_price,last_price=?,timestamp=datetime('now','localtime') where id=?",(price,reqId))
            cursor.execute("INSERT INTO prices (ticker_id,timestamp,price,prev_price) values (?,datetime('now','localtime'),?,(select price from prices where ticker_id=? order by timestamp desc limit 1))",(reqId,price,reqId))
        elif tickType==1:
            cursor.execute("UPDATE positions set bid_price=?,timestamp=datetime('now','localtime') where id=?",(price,reqId))
        elif tickType==2:
            cursor.execute("UPDATE positions set ask_price=?,timestamp=datetime('now','localtime') where id=?",(price,reqId))
        con.commit()
        cursor.execute("UPDATE positions set spread=ask_price-bid_price where id=?",(reqId,))
        cursor.execute("UPDATE prices set movement=(select case when prev_price<price then 'yes' else 'no' end as move) where price_diff is null")
        cursor.execute("UPDATE prices set price_diff=price-prev_price where price_diff is null")
        # cursor.execute("UPDATE prices set price_diff=price-prev_price,movement=(select case when prev_price<price then 'up' else 'no' end as move) where price_diff is null")
        con.commit()
        con.close()

    def historicalData(self, reqId, bar):
        con = sqlite3.connect(os.path.join(script_dir,'trendrider.db'))
        cursor = con.cursor()
        # print("In history")
        # print(f'Time: {bar.date} Close: {bar.close}')
        # print("Bar:",bar)
        cursor.execute("UPDATE positions set last_price=?,timestamp=datetime('now','localtime') where id=?",(bar.close,reqId))
        con.commit()
        con.close()

    def nextValidId(self, orderId: int):
        super().nextValidId(orderId)
        self.nextValidOrderId = orderId + 1
        # print("NextValidId:", orderId)       

    def scannerData(self, reqId, rank, contractDetails, distance, benchmark, projection, legStr):
        con = sqlite3.connect(os.path.join(script_dir,'trendrider.db'))
        cursor = con.cursor()
        super().scannerData(reqId, rank, contractDetails, distance, benchmark, projection, legStr)
        prev = cursor.execute("SELECT * FROM positions where ticker=?",(contractDetails.contract.symbol,)).fetchall()
        if len(prev):
            cursor.execute("UPDATE positions set rank=? where ticker=?",(rank,contractDetails.contract.symbol))
        else:
            cursor.execute("INSERT INTO positions (ticker,status,rank) VALUES (?,'Scan',?)",(contractDetails.contract.symbol,rank))
        # print("ScannerData. ReqId:", reqId, "---", contractDetails.contract, "---", rank)
        con.commit()
        con.close()

def update_db():
    con = sqlite3.connect(os.path.join(script_dir,'trendrider.db'))
    cursor = con.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS positions (id INTEGER PRIMARY KEY, ticker TEXT, trigger_price REAL, avg_price REAL, status TEXT, stop_limit REAL, profit_target REAL, position INTEGER, last_price REAL, prev_last_price REAL, ask_price REAL, bid_price REAL, spread REAL, final_price REAL, start_price REAL, pnl REAL, total_val REAL, total_pnl REAL, stop_loss_spread REAL, timestamp TEXT, buy_time TEXT, sold_time TEXT,rank INTEGER, volume INTEGER)")
    cursor.execute("CREATE TABLE IF NOT EXISTS prices (id INTEGER PRIMARY KEY, ticker_id INTEGER, price REAL, prev_price REAL, movement TEXT, price_diff REAL, timestamp TEXT, volume INTEGER)")
    cursor.execute("CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY, ticker TEXT, trade_id INTEGER, buy_price REAL, sell_price REAL, amount REAL, buy_timestamp TEXT, sell_timestamp TEXT, buy_total REAL, sell_total REAL, pnl REAL, status TEXT, remarks TEXT)")
    con.commit()
    con.close()

def run_loop():
    print("Running ib")
    ib.run()

running_market = []

def checkprices():
    while True:
        con = sqlite3.connect(os.path.join(script_dir,'trendrider.db'))
        cursor = con.cursor()
        # print("Checking prices in background")
        positions = cursor.execute("SELECT * FROM positions ORDER BY timestamp desc").fetchall()
        for pos in positions:
            if pos[1] not in running_market:
                # print("Position:",pos)
                contract = Contract()
                contract.symbol = pos[1]
                contract.secType = 'STK'
                contract.exchange = 'SMART'
                contract.currency = 'USD'
                ib.reqMktData(pos[0], contract, '', False, False, [])
                # ib.reqHistoricalData(pos[0],contract,'','1 D','10 secs','TRADES',0,2,False,[])
                running_market.append(pos[1])
        to_buys = cursor.execute("SELECT id,ticker,last_price FROM positions where status='Buy' and last_price > trigger_price ORDER BY timestamp desc").fetchall()
        for to_buy in to_buys:
            print("Buying ",to_buy[1])
            totalpos = math.floor(max_trade/to_buy[2])
            totalval = totalpos * round(to_buy[2],2)
            order = Order()
            order.action = "Buy"
            order.orderType = "LMT"
            order.totalQuantity = totalpos
            order.lmtPrice = round(to_buy[2],2)
            order.outsideRth = True
            order.eTradeOnly = False
            order.firmQuoteOnly = False
            contract = Contract()
            contract.symbol = to_buy[1]
            contract.secType = 'STK'
            contract.exchange = 'SMART'
            contract.currency = 'USD'
            trade_remarks = ib.placeOrder(ib.nextValidOrderId,contract,order)
            cursor.execute("UPDATE positions set status='Bought',timestamp=datetime('now','localtime'),buy_time=datetime('now','localtime'),start_price=last_price,position=?,total_val=? where id=?",(totalpos,totalval,to_buy[0]))
            con.commit()
            # cursor.execute("CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY, ticker TEXT, trade_id INTEGER, buy_price REAL, sell_price REAL, amount REAL, timestamp TEXT, buy_total REAL, sell_total REAL, pnl REAL, status TEXT, remarks TEXT)")
            cursor.execute("insert into trades (ticker, trade_id, buy_price, amount, buy_timestamp, buy_total, status, remarks) values (?,?,?,?,datetime('now','localtime'),?,?,?)",(to_buy[1],ib.nextValidOrderId,round(to_buy[2],2),totalpos,totalval,'New',trade_remarks))
            con.commit()
            ib.nextValidOrderId += 1

        to_stops = cursor.execute("SELECT id,ticker,last_price,position FROM positions where status='Bought' and last_price < stop_limit ORDER BY timestamp desc").fetchall()
        for to_stop in to_stops:
            print("Selling ",to_stop[1])
            order = Order()
            order.action = "Sell"
            order.orderType = "LMT"
            order.totalQuantity = to_stop[3]
            order.lmtPrice = round(to_stop[2],2)
            sell_total = round(to_stop[2],2) * to_stop[3]
            order.outsideRth = True
            order.eTradeOnly = False
            order.firmQuoteOnly = False
            contract = Contract()
            contract.symbol = to_stop[1]
            contract.secType = 'STK'
            contract.exchange = 'SMART'
            contract.currency = 'USD'
            trade_remarks = ib.placeOrder(ib.nextValidOrderId,contract,order)
            cursor.execute("UPDATE positions set status='Stopped',timestamp=datetime('now','localtime'),sold_time=datetime('now','localtime'),final_price=last_price,pnl=last_price-start_price,total_pnl=position*last_price where id=?",(to_stop[0],))
            con.commit()
            cursor.execute("update trades set sell_price=?,sell_timestamp=datetime('now','localtime'), sell_total=?, status=?, remarks=? where ticker=? and sell_price is null",(round(to_stop[2],2),sell_total,'Complete',trade_remarks,to_stop[1]))
            con.commit()
            ib.nextValidOrderId += 1

        cursor.execute("UPDATE positions set stop_limit=last_price-stop_loss_spread where last_price-stop_loss_spread>stop_limit and status='Bought'")
        con.commit()
        cursor.execute("update trades set pnl=sell_total-buy_total where status='Complete' and pnl is null")
        con.commit()

        cancel_market_query = "SELECT positions.ticker,ticker_id,sum(price_diff) as jumlah,positions.status FROM prices,positions where ticker_id=positions.id group by ticker_id having jumlah < 0 or jumlah is null  order by jumlah asc"
        to_cancels = cursor.execute(cancel_market_query)
        cancel_ids = []
        cancel_tickers = []
        for to_cancel in to_cancels:
            if to_cancel[3]=='Scan':
                cancel_ids.append(to_cancel[1])
                cancel_tickers.append(to_cancel[0])
        for id in cancel_ids:
            ib.cancelMktData(id)
            cursor.execute("DELETE from positions where id=?",(id,))
            cursor.execute("DELETE from prices where ticker_id=?",(id,))
            con.commit()
        for tick in cancel_tickers:
            running_market.remove(tick)

        # to_profits = cursor.execute("SELECT * FROM positions where status='Bought' and last_price > profit_target ORDER BY timestamp desc").fetchall()
        # for to_profit in to_profits:
        #     print("Selling ",to_profit[1])
        #     cursor.execute("UPDATE positions set status='Profit',timestamp=datetime('now') where id=?",(to_profit[0],))
        #     con.commit()
        time.sleep(1)
        con.close()

# def usStkScan(asset_type="STK",asset_loc="STK.US.MAJOR",scan_code="TOP_PERC_GAIN"):
def usStkScan(asset_type="STK",asset_loc="STK.US.MAJOR",scan_code="HOT_BY_VOLUME"):
    scanSub = ScannerSubscription()
    scanSub.numberOfRows = 50
    scanSub.abovePrice = 1 
    scanSub.belowPrice = 20
    scanSub.aboveVolume = 1000
    scanSub.instrument = asset_type
    scanSub.locationCode = asset_loc
    scanSub.scanCode = scan_code
    return scanSub

ib = IBapi()

api_thread = threading.Thread(target=run_loop, daemon=True)
price_thread = threading.Thread(target=checkprices, daemon=True)
script_path = os.path.abspath(__file__)
script_dir = os.path.dirname(script_path)
profit_spread = 0.5
stop_spread = 0.1
max_trade = 100


@asynccontextmanager
async def lifespan(app: FastAPI):
    update_db()
    ib.connect('127.0.0.1',7497,123)
    ib.reqIds(-1)
    api_thread.start()
    price_thread.start()
    ib.reqScannerSubscription(1, usStkScan(), [], [])
    yield
    ib.disconnect()

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
def web_root(request: Request):
    return templates.TemplateResponse(
        request=request, name="index.html", context={}
    )

@app.get("/positions", response_class=HTMLResponse)
def web_positions(request: Request):
    con = sqlite3.connect(os.path.join(script_dir,'trendrider.db'))
    cursor = con.cursor()
    positions = cursor.execute("SELECT id,ticker,status,position,trigger_price,stop_limit,last_price,start_price,final_price,total_val,total_pnl FROM positions where status!='Scan' ORDER BY ticker").fetchall()
    con.close()
    return templates.TemplateResponse(
        request=request, name="positions.html", context={'positions':positions}
    )

@app.get("/scanner", response_class=HTMLResponse)
def web_scanner(request: Request):
    scan_con = sqlite3.connect(os.path.join(script_dir,'trendrider.db'))
    scan_cursor = scan_con.cursor()
    query = "SELECT ticker,last_price,prev_last_price,volume FROM positions ORDER BY volume desc, rank desc limit 10"
    scanner_results = scan_cursor.execute(query).fetchall()
    return templates.TemplateResponse(
        request=request, name="scanner.html", context={'scanners':scanner_results}
    )

@app.get("/top_change", response_class=HTMLResponse)
def web_top_change(request: Request):
    scan_con = sqlite3.connect(os.path.join(script_dir,'trendrider.db'))
    scan_cursor = scan_con.cursor()
    top_query = "SELECT positions.ticker,ticker_id,sum(price_diff) as jumlah,positions.volume,positions.last_price FROM prices,positions where ticker_id=positions.id group by ticker_id having jumlah>0 order by jumlah desc limit 10"
    scanner_results = scan_cursor.execute(top_query).fetchall()
    return templates.TemplateResponse(
        request=request, name="top_change.html", context={'scanners':scanner_results}
    )

@app.post("/buy")
def buy_ticker(request:Request,ticker: Annotated[str, Form()],price: Annotated[str, Form()]):
    ticker = ticker.upper()
    con = sqlite3.connect(os.path.join(script_dir,'trendrider.db'))
    cursor = con.cursor()
    prev = cursor.execute("SELECT * FROM positions where ticker=?",(ticker,)).fetchall()
    curstop_spread = float(price) * stop_spread
    if curstop_spread > 0.5:
        curstop_spread = 0.5
    if len(prev):
        print("Already bought ticker:",ticker," Price:",price)
        cursor.execute("UPDATE positions set trigger_price=?,stop_limit=?,stop_loss_spread=?,profit_target=?,status='Buy',timestamp=datetime('now','localtime') where id=?",(float(price),float(price)*(1-stop_spread),curstop_spread,float(price)+profit_spread,prev[0][0]))
    else:
        print("Buy ticker:",ticker," Price:",price)
        cursor.execute("INSERT INTO positions (ticker,trigger_price,stop_limit,stop_loss_spread,profit_target,status,timestamp) VALUES (?,?,?,?,?,'Buy',datetime('now','localtime'))",(ticker,float(price),float(price)*(1-stop_spread),curstop_spread,float(price)+profit_spread))
    con.commit()
    con.close()
    return templates.TemplateResponse(
        request=request, name="buy.html", context={'ticker':ticker,'price':price}
    )

@app.get("/cancel/{ticker}")
def cancel_ticker(ticker:str):
    con = sqlite3.connect(os.path.join(script_dir,'trendrider.db'))
    cursor = con.cursor()
    cursor.execute("UPDATE positions set status='Cancelled' where ticker=?",(ticker,))
    con.commit()
    con.close()
    return RedirectResponse("/positions")

@app.get("/test")
def web_test(request:Request):
    return templates.TemplateResponse(
        request=request,name="test.html",context={}
    )
