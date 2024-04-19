from ibapi.client import EClient, ScannerSubscription
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order

class IBapi(EWrapper, EClient):
    def __init__(self):
        print("Initing myself")
        EClient.__init__(self,self)

    def scannerParameters(self, xml: str):
        print("Scanner params received")
        super().scannerParameters(xml)
        open('scanner_params.xml','w').write(xml)

    def scannerData(self, reqId, rank, contractDetails, distance, benchmark, projection, legStr):
        super().scannerData(reqId, rank, contractDetails, distance, benchmark, projection, legStr)
        print("===========================================================")
        print("ScannerData. ReqId:", reqId, "---", contractDetails.contract, "---", rank)
        print("Ticker:",contractDetails.contract.symbol)

def usStkScan(asset_type="STK",asset_loc="STK.US.MAJOR",scan_code="HOT_BY_VOLUME"):
    scanSub = ScannerSubscription()
    scanSub.numberOfRows = 50
    scanSub.abovePrice = 1 
    scanSub.belowPrice = 20
    scanSub.aboveVolume = 1000000
    scanSub.instrument = asset_type
    scanSub.locationCode = asset_loc
    scanSub.scanCode = scan_code
    return scanSub

ib = IBapi()
ib.connect('127.0.0.1',7497,2234)
ib.reqScannerSubscription(1, usStkScan(), [], [])
# ib.reqScannerParameters()
ib.run()
