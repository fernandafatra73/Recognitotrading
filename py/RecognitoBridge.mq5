//+------------------------------------------------------------------+
//|  RecognitoBridge.mq5                                              |
//|  Recognito Trading Fernanda - Auto trade MT5 (Exness)             |
//|  Created By: Fernanda Fatria Fatra,SST.MM                         |
//|                                                                  |
//|  Aturan (semua eksekusi harga pasar, pada candle tertutup):       |
//|   - Bullish Engulfing (BuE) -> BUY 0.01                           |
//|     BUY ditutup pada candle ke-3 Three Black Crows (BBC / 3BC)    |
//|   - Bearish Engulfing (BeE) -> SELL 0.01                          |
//|     SELL ditutup pada candle ke-3 Three White Soldiers (BWS / 3WS)|
//|   - CHoCH -> buka posisi searah arah baru (berlawanan tren lama): |
//|     tren naik lalu CHoCH bearish -> SELL, tren turun -> BUY       |
//|   - Berulang terus; bisa dihentikan dari aplikasi atau tombol     |
//|     di chart MT5.                                                 |
//|  Komunikasi dengan aplikasi lewat folder Common\Files MT5:        |
//|   RecognitoCmd.txt (perintah dari aplikasi)                       |
//|   RecognitoStatus.txt (status dari EA)                            |
//+------------------------------------------------------------------+
#property copyright "Created By: Fernanda Fatria Fatra,SST.MM"
#property version   "1.10"
#property description "Recognito Trading Fernanda: BuE/CHoCH naik -> BUY (tutup di BBC ke-3), BeE/CHoCH turun -> SELL (tutup di BWS ke-3)"

#include <Trade\Trade.mqh>

input double InpLot          = 0.01;     // Lot per posisi
input int    InpSwingLen     = 3;        // Panjang swing BOS/CHoCH (sama dengan aplikasi)
input int    InpHistory      = 500;      // Jumlah candle untuk analisa struktur
input double InpSafetySLPips = 300;      // SL pengaman dalam pips (1 pip = 0.10), 0 = tanpa SL
input bool   InpStartOn      = false;    // Auto trade langsung aktif saat EA dipasang
input bool   InpFollowApp    = true;     // Ikuti tombol ON/OFF dari aplikasi
input long   InpMagic        = 20261029; // Magic number
input int    InpSlippage     = 30;       // Slippage (points)

#define CMD_FILE    "RecognitoCmd.txt"
#define STATUS_FILE "RecognitoStatus.txt"
#define PFX         "RTF_"

CTrade   trade;
bool     gAuto     = false;
double   gLotBuy   = 0.01;
double   gLotSell  = 0.01;
datetime gLastBar  = 0;
string   gLastCmd  = "";
string   gLog[];
int      gTrend    = 0;
string   gLastEvt  = "-";

void UpdateButtons();

//+------------------------------------------------------------------+
void AddLog(string s)
  {
   string line = TimeToString(TimeLocal(), TIME_DATE | TIME_SECONDS) + "  " + s;
   int n = ArraySize(gLog);
   if(n >= 40)
     {
      for(int i = 1; i < n; i++) gLog[i - 1] = gLog[i];
      n--;
     }
   ArrayResize(gLog, n + 1);
   gLog[n] = line;
   Print(s);
  }

//+------------------------------------------------------------------+
double PipSize()
  {
   if(StringFind(_Symbol, "XAU") >= 0 || StringFind(_Symbol, "GOLD") >= 0) return 0.1;
   return 10 * _Point;
  }

double NormLot(double v)
  {
   double mn = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double mx = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double st = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(st <= 0) st = 0.01;
   v = MathRound(v / st) * st;
   v = MathMax(mn, MathMin(mx, v));
   return NormalizeDouble(v, 2);
  }

int CountPos(ENUM_POSITION_TYPE type)
  {
   int c = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == type) c++;
     }
   return c;
  }

void ClosePos(int which, string reason)   // which: 1 = BUY, -1 = SELL, 0 = semua
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      ENUM_POSITION_TYPE t = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      if(which == 1 && t != POSITION_TYPE_BUY) continue;
      if(which == -1 && t != POSITION_TYPE_SELL) continue;
      double pr = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
      string nm = (t == POSITION_TYPE_BUY) ? "BUY" : "SELL";
      if(trade.PositionClose(tk))
         AddLog(StringFormat("%s #%I64u DITUTUP (%s)  P/L %.2f", nm, tk, reason, pr));
      else
         AddLog(StringFormat("GAGAL tutup %s #%I64u: %s", nm, tk, trade.ResultRetcodeDescription()));
     }
  }

void OpenPos(int dir, string reason)
  {
   double lot = NormLot(dir > 0 ? gLotBuy : gLotSell);
   double pip = PipSize();
   double price = (dir > 0) ? SymbolInfoDouble(_Symbol, SYMBOL_ASK) : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sl = 0;
   if(InpSafetySLPips > 0)
     {
      double dist = InpSafetySLPips * pip;
      double minDist = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
      if(dist < minDist) dist = minDist;
      sl = NormalizeDouble((dir > 0) ? price - dist : price + dist, _Digits);
     }
   bool ok;
   if(dir > 0) ok = trade.Buy(lot, _Symbol, 0, sl, 0, "RTF " + reason);
   else        ok = trade.Sell(lot, _Symbol, 0, sl, 0, "RTF " + reason);
   if(ok && (trade.ResultRetcode() == TRADE_RETCODE_DONE || trade.ResultRetcode() == TRADE_RETCODE_PLACED))
      AddLog(StringFormat("%s %.2f DIBUKA @ %s (%s)%s", (dir > 0 ? "BUY" : "SELL"), lot,
             DoubleToString(trade.ResultPrice(), _Digits), reason,
             (sl > 0 ? "  SL " + DoubleToString(sl, _Digits) : "")));
   else
      AddLog(StringFormat("GAGAL buka %s: %s", (dir > 0 ? "BUY" : "SELL"), trade.ResultRetcodeDescription()));
  }

//+------------------------------------------------------------------+
//| Struktur pasar sama persis dengan aplikasi (swing L candle)       |
//+------------------------------------------------------------------+
bool ThreeCandles(const MqlRates &r[], int n, int dir)   // sama dengan definisi 3WS / 3BC di aplikasi
  {
   int a = n - 1;
   if(n < 14) return false;
   double avgB = 0;
   for(int k = a - 10; k < a; k++) avgB += MathAbs(r[k].close - r[k].open);
   avgB /= 10;
   for(int i = a - 2; i <= a; i++)
     {
      bool col = (dir > 0) ? (r[i].close > r[i].open) : (r[i].close < r[i].open);
      if(!col || MathAbs(r[i].close - r[i].open) <= 0.6 * avgB) return false;
     }
   if(dir > 0) return (r[a - 1].close > r[a - 2].close) && (r[a].close > r[a - 1].close);
   return (r[a - 1].close < r[a - 2].close) && (r[a].close < r[a - 1].close);
  }

void Structure(const MqlRates &r[], int n, int L, bool &bosLast, bool &chochLast, int &chochDir)
  {
   double sh = 0, sl = 0;
   int shi = -1, sli = -1, trend = 0;
   bool shB = true, slB = true;
   bosLast = false;
   chochLast = false;
   chochDir = 0;
   for(int i = 0; i < n; i++)
     {
      int j = i - L;
      if(j >= L)
        {
         bool isH = true, isL = true;
         for(int k = j - L; k <= j + L; k++)
            if(k != j)
              {
               if(r[k].high > r[j].high) isH = false;
               if(r[k].low < r[j].low) isL = false;
              }
         if(isH) { sh = r[j].high; shi = j; shB = false; }
         if(isL) { sl = r[j].low;  sli = j; slB = false; }
        }
      if(shi >= 0 && !shB && r[i].close > sh)
        {
         bool ch = (trend == -1);
         if(i == n - 1)
           {
            if(ch) { chochLast = true; chochDir = 1; } else bosLast = true;
            gLastEvt = (ch ? "CHoCH" : "BOS") + " BULLISH @ " + DoubleToString(sh, _Digits);
           }
         trend = 1;
         shB = true;
        }
      if(sli >= 0 && !slB && r[i].close < sl)
        {
         bool ch = (trend == 1);
         if(i == n - 1)
           {
            if(ch) { chochLast = true; chochDir = -1; } else bosLast = true;
            gLastEvt = (ch ? "CHoCH" : "BOS") + " BEARISH @ " + DoubleToString(sl, _Digits);
           }
         trend = -1;
         slB = true;
        }
     }
   gTrend = trend;
  }

void Analyze(bool allowTrade)
  {
   MqlRates r[];
   ArraySetAsSeries(r, false);
   int n = CopyRates(_Symbol, _Period, 1, InpHistory, r);   // hanya candle tertutup
   if(n < 50) return;
   bool bos, choch;
   int chochDir;
   Structure(r, n, InpSwingLen, bos, choch, chochDir);

   int a = n - 1, b = n - 2;
   double bodyA = MathAbs(r[a].close - r[a].open), bodyB = MathAbs(r[b].close - r[b].open);
   bool bue = (r[b].close < r[b].open) && (r[a].close > r[a].open) &&
              (r[a].close >= r[b].open) && (r[a].open <= r[b].close) && (bodyA > bodyB);
   bool bee = (r[b].close > r[b].open) && (r[a].close < r[a].open) &&
              (r[a].close <= r[b].open) && (r[a].open >= r[b].close) && (bodyA > bodyB);
   bool tbc = ThreeCandles(r, n, -1);   // Three Black Crows (BBC / 3BC)
   bool tws = ThreeCandles(r, n, 1);    // Three White Soldiers (BWS / 3WS)

   if(!allowTrade) return;

   // keluar: BUY ditutup di candle ke-3 Three Black Crows, SELL di candle ke-3 Three White Soldiers
   if(tbc) AddLog("Three Black Crows (BBC) terdeteksi - candle ke-3");
   if(tws) AddLog("Three White Soldiers (BWS) terdeteksi - candle ke-3");
   if(tbc && CountPos(POSITION_TYPE_BUY) > 0)  ClosePos(1, "ketemu BBC ke-3");
   if(tws && CountPos(POSITION_TYPE_SELL) > 0) ClosePos(-1, "ketemu BWS ke-3");

   if(bue)   AddLog("Bullish Engulfing (BuE) terdeteksi");
   if(bee)   AddLog("Bearish Engulfing (BeE) terdeteksi");
   if(choch) AddLog("CHoCH terdeteksi: " + gLastEvt);
   if(!gAuto)
     {
      if(bue || bee || choch) AddLog("Auto trade OFF - tidak membuka posisi");
      return;
     }
   // masuk: BuE / CHoCH bullish (tren tadinya turun) -> BUY; BeE / CHoCH bearish (tren tadinya naik) -> SELL
   int want = 0;
   string why = "";
   if(bue)        { want = 1;  why = "BuE"; }
   else if(bee)   { want = -1; why = "BeE"; }
   else if(choch) { want = chochDir; why = (chochDir > 0 ? "CHoCH bullish (balik naik)" : "CHoCH bearish (balik turun)"); }
   if(want == 0) return;

   bool hedging = (AccountInfoInteger(ACCOUNT_MARGIN_MODE) == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING);
   if(want > 0)
     {
      if(CountPos(POSITION_TYPE_BUY) > 0) AddLog("BUY sudah terbuka - sinyal " + why + " dilewati");
      else if(!hedging && CountPos(POSITION_TYPE_SELL) > 0) AddLog("Akun netting: BUY dilewati karena masih ada SELL");
      else OpenPos(1, why);
     }
   else
     {
      if(CountPos(POSITION_TYPE_SELL) > 0) AddLog("SELL sudah terbuka - sinyal " + why + " dilewati");
      else if(!hedging && CountPos(POSITION_TYPE_BUY) > 0) AddLog("Akun netting: SELL dilewati karena masih ada BUY");
      else OpenPos(-1, why);
     }
  }

void CheckNewBar()
  {
   datetime t = iTime(_Symbol, _Period, 0);
   if(t == 0 || t == gLastBar) return;
   bool first = (gLastBar == 0);
   gLastBar = t;
   Analyze(!first);   // candle pertama saat EA dipasang hanya dianalisa, tidak ditradingkan
  }

//+------------------------------------------------------------------+
//| Perintah dari aplikasi                                            |
//+------------------------------------------------------------------+
void ReadCommand(bool initial)
  {
   if(!FileIsExist(CMD_FILE, FILE_COMMON)) return;
   int h = FileOpen(CMD_FILE, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE) return;
   string id = "", autoV = "", closeV = "", lotB = "", lotS = "";
   while(!FileIsEnding(h))
     {
      string line = FileReadString(h);
      int p = StringFind(line, "=");
      if(p < 0) continue;
      string k = StringSubstr(line, 0, p), v = StringSubstr(line, p + 1);
      StringTrimLeft(v); StringTrimRight(v);
      if(k == "ID") id = v;
      else if(k == "AUTO") autoV = v;
      else if(k == "CLOSEALL") closeV = v;
      else if(k == "LOTBUY") lotB = v;
      else if(k == "LOTSELL") lotS = v;
     }
   FileClose(h);
   if(id == "" || id == gLastCmd) return;
   gLastCmd = id;
   if(InpFollowApp && autoV != "")
     {
      bool v = (autoV == "1");
      if(v != gAuto)
        {
         gAuto = v;
         AddLog(gAuto ? "Auto trade DIAKTIFKAN dari aplikasi" : "Auto trade DIHENTIKAN dari aplikasi");
         UpdateButtons();
        }
     }
   double lb = StringToDouble(lotB), ls = StringToDouble(lotS);
   if(lb > 0 && MathAbs(lb - gLotBuy) > 1e-9)
     {
      gLotBuy = NormLot(lb);
      AddLog("Lot BUY diubah dari aplikasi: " + DoubleToString(gLotBuy, 2));
     }
   if(ls > 0 && MathAbs(ls - gLotSell) > 1e-9)
     {
      gLotSell = NormLot(ls);
      AddLog("Lot SELL diubah dari aplikasi: " + DoubleToString(gLotSell, 2));
     }
   UpdateButtons();
   if(!initial && closeV == "1")
      ClosePos(0, "perintah tutup semua dari aplikasi");
  }

void WriteStatus(bool alive)
  {
   int h = FileOpen(STATUS_FILE, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ);
   if(h == INVALID_HANDLE) return;
   double prof = 0;
   string pos = "";
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      double pr = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
      prof += pr;
      pos += StringFormat("POS=%I64u;%s;%.2f;%s;%.2f\r\n", tk,
             ((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? "BUY" : "SELL"),
             PositionGetDouble(POSITION_VOLUME), DoubleToString(PositionGetDouble(POSITION_PRICE_OPEN), _Digits), pr);
     }
   bool algo = TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && MQLInfoInteger(MQL_TRADE_ALLOWED);
   string tf = EnumToString(_Period);
   StringReplace(tf, "PERIOD_", "");
   FileWriteString(h, "EA=" + (alive ? "ON" : "OFF") + "\r\n");
   FileWriteString(h, "LOCAL=" + TimeToString(TimeLocal(), TIME_DATE | TIME_SECONDS) + "\r\n");
   FileWriteString(h, "ACCOUNT=" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + "\r\n");
   FileWriteString(h, "SERVER=" + AccountInfoString(ACCOUNT_SERVER) + "\r\n");
   FileWriteString(h, "COMPANY=" + AccountInfoString(ACCOUNT_COMPANY) + "\r\n");
   FileWriteString(h, "BALANCE=" + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2) + "\r\n");
   FileWriteString(h, "EQUITY=" + DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2) + "\r\n");
   FileWriteString(h, "CURRENCY=" + AccountInfoString(ACCOUNT_CURRENCY) + "\r\n");
   FileWriteString(h, "SYMBOL=" + _Symbol + "\r\n");
   FileWriteString(h, "TF=" + tf + "\r\n");
   FileWriteString(h, "PRICE=" + DoubleToString(SymbolInfoDouble(_Symbol, SYMBOL_BID), _Digits) + "\r\n");
   FileWriteString(h, "AUTO=" + (gAuto ? "1" : "0") + "\r\n");
   FileWriteString(h, "LOTBUY=" + DoubleToString(gLotBuy, 2) + "\r\n");
   FileWriteString(h, "LOTSELL=" + DoubleToString(gLotSell, 2) + "\r\n");
   FileWriteString(h, "ALGO=" + (algo ? "1" : "0") + "\r\n");
   FileWriteString(h, "TREND=" + IntegerToString(gTrend) + "\r\n");
   FileWriteString(h, "LASTEVT=" + gLastEvt + "\r\n");
   FileWriteString(h, "POS_BUY=" + IntegerToString(CountPos(POSITION_TYPE_BUY)) + "\r\n");
   FileWriteString(h, "POS_SELL=" + IntegerToString(CountPos(POSITION_TYPE_SELL)) + "\r\n");
   FileWriteString(h, "PROFIT=" + DoubleToString(prof, 2) + "\r\n");
   FileWriteString(h, pos);
   for(int i = 0; i < ArraySize(gLog); i++) FileWriteString(h, "LOG=" + gLog[i] + "\r\n");
   FileClose(h);
  }

//+------------------------------------------------------------------+
//| Tombol di chart MT5                                               |
//+------------------------------------------------------------------+
void MakeButton(string name, string text, int x, int y, int w, color bg, color fg,
                ENUM_BASE_CORNER corner = CORNER_LEFT_UPPER)
  {
   if(ObjectFind(0, name) < 0) ObjectCreate(0, name, OBJ_BUTTON, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_CORNER, corner);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, 26);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, bg);
   ObjectSetInteger(0, name, OBJPROP_COLOR, fg);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 9);
   ObjectSetInteger(0, name, OBJPROP_STATE, false);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
  }

void UpdateButtons()
  {
   MakeButton(PFX + "AUTO", gAuto ? "AUTO TRADE: ON" : "AUTO TRADE: OFF", 10, 30, 150,
              gAuto ? clrLimeGreen : clrDimGray, clrWhite);
   MakeButton(PFX + "CLOSE", "TUTUP SEMUA", 166, 30, 110, clrCrimson, clrWhite);
   // kiri bawah: STOP FER + lot aktif
   MakeButton(PFX + "STOP", "STOP FER", 10, 40, 100, clrRed, clrWhite, CORNER_LEFT_LOWER);
   MakeButton(PFX + "LOTS", StringFormat("Lot BUY %.2f  |  Lot SELL %.2f", gLotBuy, gLotSell),
              116, 40, 220, clrDarkSlateGray, clrWhite, CORNER_LEFT_LOWER);
   ChartRedraw();
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpSlippage);
   trade.SetTypeFillingBySymbol(_Symbol);
   gAuto = InpStartOn;
   gLotBuy = NormLot(InpLot);
   gLotSell = NormLot(InpLot);
   ReadCommand(true);
   AddLog("EA Recognito aktif di " + _Symbol + " " + EnumToString(_Period) + (gAuto ? " (auto ON)" : " (auto OFF)"));
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
      AddLog("PERINGATAN: tombol Algo Trading di MT5 masih MATI");
   UpdateButtons();
   EventSetTimer(1);
   CheckNewBar();
   WriteStatus(true);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   ObjectsDeleteAll(0, PFX);
   AddLog("EA dihentikan");
   WriteStatus(false);
   Comment("");
  }

void OnTick()
  {
   CheckNewBar();
  }

void OnTimer()
  {
   ReadCommand(false);
   CheckNewBar();
   WriteStatus(true);
   Comment(StringFormat("Recognito Trading Fernanda\nAuto trade: %s   Tren: %s\nBUY: %d   SELL: %d\nEvent terakhir: %s",
           (gAuto ? "ON" : "OFF"), (gTrend > 0 ? "BULLISH" : gTrend < 0 ? "BEARISH" : "-"),
           CountPos(POSITION_TYPE_BUY), CountPos(POSITION_TYPE_SELL), gLastEvt));
  }

void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
  {
   if(id != CHARTEVENT_OBJECT_CLICK) return;
   if(sparam == PFX + "AUTO")
     {
      gAuto = !gAuto;
      AddLog(gAuto ? "Auto trade DIAKTIFKAN dari MT5" : "Auto trade DIHENTIKAN dari MT5");
      UpdateButtons();
      WriteStatus(true);
     }
   else if(sparam == PFX + "CLOSE")
     {
      ClosePos(0, "tombol tutup semua di MT5");
      UpdateButtons();
     }
   else if(sparam == PFX + "STOP")
     {
      gAuto = false;
      AddLog("STOP FER ditekan di MT5 - auto trade DIHENTIKAN");
      UpdateButtons();
      WriteStatus(true);
     }
   else if(sparam == PFX + "LOTS")
      UpdateButtons();
  }
//+------------------------------------------------------------------+
