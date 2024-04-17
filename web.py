from typing import Union,Annotated

from fastapi import FastAPI, Response, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pydantic import BaseModel

import sqlite3
import math

from ibapi.client import EClient
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

    def tickPrice(self, reqId, tickType, price, attrib):
        # print("In tickprice")
        # print('Id:',reqId,' Price:', price,' TickType:',tickType,' attrib:',attrib)
        con = sqlite3.connect(os.path.join(script_dir,'trendrider.db'))
        cursor = con.cursor()
        if tickType==4:
            cursor.execute("UPDATE positions set last_price=?,timestamp=datetime('now') where id=?",(price,reqId))
        elif tickType==1:
            cursor.execute("UPDATE positions set bid_price=?,timestamp=datetime('now') where id=?",(price,reqId))
        elif tickType==2:
            cursor.execute("UPDATE positions set ask_price=?,timestamp=datetime('now') where id=?",(price,reqId))
        con.commit()
        cursor.execute("UPDATE positions set spread=ask_price-bid_price where id=?",(reqId,))
        con.commit()
        con.close()

    def historicalData(self, reqId, bar):
        con = sqlite3.connect(os.path.join(script_dir,'trendrider.db'))
        cursor = con.cursor()
        # print("In history")
        # print(f'Time: {bar.date} Close: {bar.close}')
        # print("Bar:",bar)
        cursor.execute("UPDATE positions set last_price=?,timestamp=datetime('now') where id=?",(bar.close,reqId))
        con.commit()
        con.close()

    def nextValidId(self, orderId: int):
        super().nextValidId(orderId)
        self.nextValidOrderId = orderId + 1
        print("NextValidId:", orderId)       

def update_db():
    con = sqlite3.connect(os.path.join(script_dir,'trendrider.db'))
    cursor = con.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS positions (id INTEGER PRIMARY KEY, ticker TEXT, trigger_price REAL, avg_price REAL, status TEXT, stop_limit REAL, profit_target REAL, position INTEGER, last_price REAL, ask_price REAL, bid_price REAL, spread REAL, final_price REAL, start_price REAL, pnl REAL, total_val REAL, total_pnl REAL, stop_loss_spread REAL, timestamp)")
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
        to_buys = cursor.execute("SELECT id,ticker,last_price FROM positions where status='New' and last_price > trigger_price ORDER BY timestamp desc").fetchall()
        for to_buy in to_buys:
            print("Buying ",to_buy[1])
            totalpos = math.floor(max_trade/to_buy[2])
            totalval = totalpos * to_buy[2]
            order = Order()
            order.action = "Buy"
            order.orderType = "LMT"
            order.totalQuantity = totalpos
            order.lmtPrice = to_buy[2]
            order.outsideRth = True
            order.eTradeOnly = False
            order.firmQuoteOnly = False
            contract = Contract()
            contract.symbol = to_buy[1]
            contract.secType = 'STK'
            contract.exchange = 'SMART'
            contract.currency = 'USD'
            print("Order done:" ,ib.placeOrder(ib.nextValidOrderId,contract,order))
            ib.nextValidOrderId += 1
            cursor.execute("UPDATE positions set status='Bought',timestamp=datetime('now'),start_price=last_price,position=?,total_val=? where id=?",(totalpos,totalval,to_buy[0]))
            con.commit()

        to_stops = cursor.execute("SELECT id,ticker,last_price,position FROM positions where status='Bought' and last_price < stop_limit ORDER BY timestamp desc").fetchall()
        for to_stop in to_stops:
            print("Selling ",to_stop[1])
            order = Order()
            order.action = "Sell"
            order.orderType = "LMT"
            order.totalQuantity = to_stop[3]
            order.lmtPrice = to_stop[2]
            order.outsideRth = True
            order.eTradeOnly = False
            order.firmQuoteOnly = False
            contract = Contract()
            contract.symbol = to_stop[1]
            contract.secType = 'STK'
            contract.exchange = 'SMART'
            contract.currency = 'USD'
            print("Order done:",ib.placeOrder(ib.nextValidOrderId,contract,order))
            ib.nextValidOrderId += 1
            cursor.execute("UPDATE positions set status='Stopped',timestamp=datetime('now'),final_price=last_price,pnl=last_price-start_price,total_pnl=position*last_price where id=?",(to_stop[0],))
            con.commit()

        cursor.execute("UPDATE positions set stop_limit=last_price-stop_loss_spread where last_price-stop_loss_spread>stop_limit and status='Bought'")
        con.commit()
        # to_profits = cursor.execute("SELECT * FROM positions where status='Bought' and last_price > profit_target ORDER BY timestamp desc").fetchall()
        # for to_profit in to_profits:
        #     print("Selling ",to_profit[1])
        #     cursor.execute("UPDATE positions set status='Profit',timestamp=datetime('now') where id=?",(to_profit[0],))
        #     con.commit()
        time.sleep(1)
        con.close()

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
    positions = cursor.execute("SELECT id,ticker,status,position,trigger_price,stop_limit,last_price,start_price,final_price,total_val,total_pnl FROM positions ORDER BY ticker").fetchall()
    return templates.TemplateResponse(
        request=request, name="positions.html", context={'positions':positions}
    )

@app.post("/buy")
def buy_ticker(request:Request,ticker: Annotated[str, Form()],price: Annotated[str, Form()]):
    con = sqlite3.connect(os.path.join(script_dir,'trendrider.db'))
    cursor = con.cursor()
    prev = cursor.execute("SELECT * FROM positions where ticker=?",(ticker,)).fetchall()
    if len(prev):
        print("Already bought ticker:",ticker," Price:",price)
        cursor.execute("UPDATE positions set trigger_price=?,stop_limit=?,stop_loss_spread=?,profit_target=?,status='New',timestamp=datetime('now') where id=?",(float(price),float(price)*(1-stop_spread),float(price)*stop_spread,float(price)+profit_spread,prev[0][0]))
    else:
        print("Buy ticker:",ticker," Price:",price)
        cursor.execute("INSERT INTO positions (ticker,trigger_price,stop_limit,stop_loss_spread,profit_target,status,timestamp) VALUES (?,?,?,?,?,'New',datetime('now'))",(ticker,float(price),float(price)*(1-stop_spread),float(price)*stop_spread,float(price)+profit_spread))
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
