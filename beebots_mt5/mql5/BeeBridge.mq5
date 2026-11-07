//+------------------------------------------------------------------+
//| BeeBridge.mq5 - file bridge for beebots (demo-only unless AllowLive). |
//| Reads Files/beebots/in/cmd_*.json, writes Files/beebots/out/resp_*.json      |
//+------------------------------------------------------------------+
#property strict
#include <Trade/Trade.mqh>
input long   DemoLogin  = 0;      // VPS: set to YOUR MT5 login (0 = refuse)
input string DemoServer = "";     // VPS: set to YOUR server name exactly
input bool   AllowLive  = false;  // demo-only guard; true only together with BEEBOTS_ALLOW_LIVE in .env
input double MaxSlFrac  = 0.25;
input int    MaxPos     = 3;   // capped at 3 in code (owner rule 2026-10-28)
CTrade trade;

string JStr(string j,string k){int p=StringFind(j,"\""+k+"\"");if(p<0)return "";p=StringFind(j,":",p)+1;
  while(StringGetCharacter(j,p)==' ')p++; bool q=StringGetCharacter(j,p)=='"'; if(q)p++;
  int e=p; while(e<StringLen(j)){ushort c=StringGetCharacter(j,e); if(q?c=='"':(c==','||c=='}'))break; e++;}
  return StringSubstr(j,p,e-p);}
double JNum(string j,string k){return StringToDouble(JStr(j,k));}

bool Guard(){ return AccountInfoInteger(ACCOUNT_LOGIN)==DemoLogin
  && AccountInfoString(ACCOUNT_SERVER)==DemoServer
  && (AllowLive || AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO); }

// Startup race fix: after a terminal restart the EA can load before the account reconnects. While the terminal is not
// connected (or login/server still empty) wait up to 90 s, re-checking every second; a connected WRONG account still refuses.
bool   gWaiting=false; datetime gWaitStart=0;
bool AccountReady(){ return TerminalInfoInteger(TERMINAL_CONNECTED) && AccountInfoInteger(ACCOUNT_LOGIN)!=0 && AccountInfoString(ACCOUNT_SERVER)!=""; }
int OnInit(){ if(DemoLogin==0||DemoServer==""){Print("BeeBridge: DemoLogin/DemoServer not set - refusing");return INIT_FAILED;}
  if(Guard()){ EventSetMillisecondTimer(200); Print("BeeBridge: account ",DemoLogin,"@",DemoServer," ready"); return INIT_SUCCEEDED; }
  if(AccountReady()){Print("BeeBridge: account ",AccountInfoInteger(ACCOUNT_LOGIN),"@",AccountInfoString(ACCOUNT_SERVER)," is not ",DemoLogin,"@",DemoServer,AllowLive?"":" (demo only)"," - refusing");return INIT_FAILED;}
  gWaiting=true; gWaitStart=TimeLocal(); Print("BeeBridge: account not connected yet - waiting up to 90s"); EventSetTimer(1); return INIT_SUCCEEDED; }
bool WaitTick(){ // true while still waiting (no commands served)
  if(!gWaiting) return false;
  if(Guard()){ gWaiting=false; EventKillTimer(); EventSetMillisecondTimer(200); Print("BeeBridge: account ",DemoLogin,"@",DemoServer," ready"); return true; }
  if(AccountReady() || TimeLocal()-gWaitStart>90){ Print("BeeBridge: account check failed after wait (",AccountInfoInteger(ACCOUNT_LOGIN),"@",AccountInfoString(ACCOUNT_SERVER),") - removing"); EventKillTimer(); ExpertRemove(); }
  return true; }
void OnDeinit(const int r){EventKillTimer();}

void Reply(string id,string body){int h=FileOpen("beebots\\out\\resp_"+id+".json",FILE_WRITE|FILE_TXT|FILE_ANSI);
  if(h!=INVALID_HANDLE){FileWriteString(h,body);FileClose(h);}}

// Counts only beebots positions (magic 7700-7799: bees 7701-7703, director 7711-7713; evolved candidates 5301xx-5303xx); the owner's manual trades are not counted or touched.
int CountPos(string sym){int n=0;for(int i=PositionsTotal()-1;i>=0;i--)if(PositionGetSymbol(i)==sym){long m=PositionGetInteger(POSITION_MAGIC);if((m>=7700&&m<=7799)||(m>530100&&m<530400&&m%100!=0))n++;}return n;}

string Open(string j){
  string sym=JStr(j,"symbol"),side=JStr(j,"side"); double vol=JNum(j,"volume"),sl=JNum(j,"sl"),tp=JNum(j,"tp");
  long magic=(long)JNum(j,"magic");
  if(sym!="XAUUSD"||MathAbs(vol-0.01)>1e-9) return "{\"ok\":false,\"error\":\"symbol/volume\"}";
  if(sl<=0||tp<=0) return "{\"ok\":false,\"error\":\"SL/TP required\"}";
  if(CountPos(sym)>=MathMin(MaxPos,3)) return "{\"ok\":false,\"error\":\"max positions\"}";
  double px= side=="buy"?SymbolInfoDouble(sym,SYMBOL_ASK):SymbolInfoDouble(sym,SYMBOL_BID);
  double loss=0; if(!OrderCalcProfit(side=="buy"?ORDER_TYPE_BUY:ORDER_TYPE_SELL,sym,vol,px,sl,loss)) return "{\"ok\":false,\"error\":\"calc\"}";
  if(-loss>MaxSlFrac*AccountInfoDouble(ACCOUNT_BALANCE)) return "{\"ok\":false,\"error\":\"SL loss > 25% balance\"}";
  trade.SetExpertMagicNumber(magic);
  bool ok= side=="buy"?trade.Buy(vol,sym,0,sl,tp,JStr(j,"comment")):trade.Sell(vol,sym,0,sl,tp,JStr(j,"comment"));
  return StringFormat("{\"ok\":%s,\"ticket\":%I64u,\"price\":%.2f,\"retcode\":%u}",ok&&trade.ResultRetcode()==TRADE_RETCODE_DONE?"true":"false",
    trade.ResultOrder(),trade.ResultPrice(),trade.ResultRetcode());}

string Close(string j){long magic=(long)JNum(j,"magic");bool ok=true;double px=0;
  for(int i=PositionsTotal()-1;i>=0;i--){ulong t=PositionGetTicket(i);
    if(PositionGetString(POSITION_SYMBOL)=="XAUUSD"&&PositionGetInteger(POSITION_MAGIC)==magic){ok&=trade.PositionClose(t);px=trade.ResultPrice();}}
  return StringFormat("{\"ok\":%s,\"price\":%.2f}",ok?"true":"false",px);}

string Positions(){string s="{\"positions\":[";bool f=true;
  for(int i=0;i<PositionsTotal();i++){ulong t=PositionGetTicket(i); if(!f)s+=",";f=false;
    s+=StringFormat("{\"ticket\":%I64u,\"symbol\":\"%s\",\"type\":\"%s\",\"volume\":%.2f,\"price_open\":%.2f,\"sl\":%.2f,\"tp\":%.2f,\"magic\":%I64d}",t,
      PositionGetString(POSITION_SYMBOL),PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY?"buy":"sell",
      PositionGetDouble(POSITION_VOLUME),PositionGetDouble(POSITION_PRICE_OPEN),
      PositionGetDouble(POSITION_SL),PositionGetDouble(POSITION_TP),PositionGetInteger(POSITION_MAGIC));}
  return s+"]}";}

// All times sent to Node are UTC epoch seconds (server time minus its GMT offset).
long SrvOff(){return (long)(TimeTradeServer()-TimeGMT());}
// Bars for M5/M15/H1/H4 only (M1 refused). Rows: [time,o,h,l,c,tick_volume], oldest first.
string Bars_(string tf,int n){ENUM_TIMEFRAMES t; if(tf=="M5")t=PERIOD_M5; else if(tf=="M15")t=PERIOD_M15; else if(tf=="H1")t=PERIOD_H1;
  else if(tf=="H4")t=PERIOD_H4; else return "{\"ok\":false,\"error\":\"tf\"}";
  long off=SrvOff(); MqlRates r[]; ArraySetAsSeries(r,false); int k=CopyRates("XAUUSD",t,0,MathMin(MathMax(n,1),1000),r); if(k<=0) return "{\"ok\":false,\"error\":\"CopyRates\"}";
  string s="{\"rows\":["; for(int i=0;i<k;i++){ if(i)s+=","; s+=StringFormat("[%I64d,%.2f,%.2f,%.2f,%.2f,%I64d]",(long)r[i].time-off,r[i].open,r[i].high,r[i].low,r[i].close,r[i].tick_volume);}
  return s+"]}";}

void OnTimer(){ if(WaitTick())return; if(!Guard())return; string f; long h=FileFindFirst("beebots\\in\\cmd_*.json",f); if(h==INVALID_HANDLE)return;
  do{ string path="beebots\\in\\"+f; int fh=FileOpen(path,FILE_READ|FILE_TXT|FILE_ANSI); if(fh==INVALID_HANDLE)continue;
    string j=""; while(!FileIsEnding(fh)) j+=FileReadString(fh); FileClose(fh); FileDelete(path);
    string id=JStr(j,"id"),op=JStr(j,"op"),r;
    if(op=="account") r=StringFormat("{\"login\":%I64d,\"server\":\"%s\",\"tradeMode\":\"%s\",\"balance\":%.2f}",AccountInfoInteger(ACCOUNT_LOGIN),
        AccountInfoString(ACCOUNT_SERVER),AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO?"demo":"real",AccountInfoDouble(ACCOUNT_BALANCE));
    else if(op=="quote") r=StringFormat("{\"bid\":%.5f,\"ask\":%.5f,\"contract_size\":%.2f,\"time\":%I64d,\"stops_level\":%d,\"freeze_level\":%d,\"point\":%.5f,\"volume_min\":%.4f,\"volume_step\":%.4f,\"volume_max\":%.2f,\"digits\":%d}",
      SymbolInfoDouble("XAUUSD",SYMBOL_BID),SymbolInfoDouble("XAUUSD",SYMBOL_ASK),SymbolInfoDouble("XAUUSD",SYMBOL_TRADE_CONTRACT_SIZE),(long)SymbolInfoInteger("XAUUSD",SYMBOL_TIME)-SrvOff(),
      (int)SymbolInfoInteger("XAUUSD",SYMBOL_TRADE_STOPS_LEVEL),(int)SymbolInfoInteger("XAUUSD",SYMBOL_TRADE_FREEZE_LEVEL),SymbolInfoDouble("XAUUSD",SYMBOL_POINT),
      SymbolInfoDouble("XAUUSD",SYMBOL_VOLUME_MIN),SymbolInfoDouble("XAUUSD",SYMBOL_VOLUME_STEP),SymbolInfoDouble("XAUUSD",SYMBOL_VOLUME_MAX),(int)SymbolInfoInteger("XAUUSD",SYMBOL_DIGITS));
    else if(op=="bars") r=Bars_(JStr(j,"tf"),(int)JNum(j,"count"));
    else if(op=="positions") r=Positions();
    else if(op=="open") r=Open(j);
    else if(op=="close") r=Close(j);
    else r="{\"ok\":false,\"error\":\"unknown op\"}";
    Reply(id,r);
  }while(FileFindNext(h,f)); FileFindClose(h);}
