import os, sys, json, time, threading, subprocess, socket, hashlib, urllib.request, urllib.parse, calendar, datetime, webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

APP='문제보고 알림'; VERSION='1.1.6'; PURPLE='#5F0080'
BASE=Path(os.getenv('APPDATA',Path.home()))/'ProblemReportAlert'
BASE.mkdir(parents=True,exist_ok=True)
SETTINGS=BASE/'settings.json'; STATE=BASE/'state.json'; PROFILE=BASE/'chrome_profile'
STATIC=(Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'static')
lock=threading.RLock(); driver=None; server=None

def load_json(p,default):
    try: return json.loads(p.read_text('utf-8'))
    except: return default

def save_json(p,obj):
    tmp=p.with_suffix('.tmp'); tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),'utf-8'); tmp.replace(p)

def defaults():
    now=datetime.date.today(); work={}
    for i in range(0,120):
        d=now+datetime.timedelta(days=i-30); work[d.isoformat()]=d.weekday()<5
    return {'sheet_url':'','slack_token':'','slack_user_id':'','interval':15,'workdays':work,'manual':None,'start':'16:00','end':'02:00','update_manifest_url':'https://raw.githubusercontent.com/Dorikkae/problem-report-alert/main/manifest.json'}

def cfg():
    d=defaults(); d.update(load_json(SETTINGS,{})); return d

def st(): return load_json(STATE,{'rows':{},'alerts':[],'last_check':None,'last_error':None,'running':True})

def put_state(s): save_json(STATE,s)

def shift_date(now=None):
    now=now or datetime.datetime.now()
    return (now.date()-datetime.timedelta(days=1) if now.hour<2 else now.date())

def scheduled(c=None):
    c=c or cfg(); now=datetime.datetime.now(); sd=shift_date(now)
    if not c.get('workdays',{}).get(sd.isoformat(),sd.weekday()<5): return False
    m=now.hour*60+now.minute; return m>=16*60 or m<2*60

def effective_running():
    c=cfg(); m=c.get('manual')
    if m is True:return True
    if m is False:return False
    return scheduled(c)

def slack(text):
    c=cfg(); token=c.get('slack_token','').strip(); uid=c.get('slack_user_id','').strip()
    if not token or not uid: raise RuntimeError('Slack Bot Token/User ID가 설정되지 않았습니다.')
    def post(url,data):
        req=urllib.request.Request(url,data=urllib.parse.urlencode(data).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/x-www-form-urlencoded'})
        with urllib.request.urlopen(req,timeout=15) as r: return json.loads(r.read())
    o=post('https://slack.com/api/conversations.open',{'users':uid})
    if not o.get('ok'): raise RuntimeError('Slack conversations.open: '+o.get('error','unknown'))
    p=post('https://slack.com/api/chat.postMessage',{'channel':o['channel']['id'],'text':text})
    if not p.get('ok'): raise RuntimeError('Slack chat.postMessage: '+p.get('error','unknown'))

def version_tuple(v):
    try: return tuple(int(x) for x in str(v).split('.')[:4])
    except: return (0,)

def check_update(install=False):
    c=cfg(); url=c.get('update_manifest_url','').strip()
    if not url: return {'ok':False,'configured':False,'error':'업데이트 서버 주소가 설정되지 않았습니다.'}
    if not url.lower().startswith('https://'): return {'ok':False,'error':'업데이트 주소는 HTTPS여야 합니다.'}
    try:
        req=urllib.request.Request(url,headers={'User-Agent':APP+'/'+VERSION})
        with urllib.request.urlopen(req,timeout=15) as r: m=json.loads(r.read().decode('utf-8'))
        latest=str(m['version']); newer=version_tuple(latest)>version_tuple(VERSION)
        if not newer: return {'ok':True,'update':False,'version':VERSION,'latest':latest}
        if not install: return {'ok':True,'update':True,'version':VERSION,'latest':latest}
        dl=str(m['url']); sha=str(m.get('sha256','')).strip().lower()
        if not dl.lower().startswith('https://'): raise RuntimeError('다운로드 주소가 HTTPS가 아닙니다.')
        req=urllib.request.Request(dl,headers={'User-Agent':APP+'/'+VERSION})
        with urllib.request.urlopen(req,timeout=120) as r: data=r.read()
        if sha and hashlib.sha256(data).hexdigest().lower()!=sha: raise RuntimeError('SHA-256 검증에 실패했습니다.')
        if not getattr(sys,'frozen',False): raise RuntimeError('자동 설치는 빌드된 EXE에서 작동합니다.')
        import tempfile
        fd,tmp=tempfile.mkstemp(suffix='.exe'); os.close(fd); Path(tmp).write_bytes(data)
        cur=os.path.abspath(sys.executable); bat=str(BASE/'apply_update.bat')
        script = (
            '@echo off\r\n'
            'setlocal\r\n'
            'set "SRC='+tmp+'"\r\n'
            'set "DST='+cur+'"\r\n'
            'timeout /t 2 /nobreak >nul\r\n'
            'for /L %%I in (1,1,20) do (\r\n'
            '  copy /y "%SRC%" "%DST%" >nul 2>&1 && goto :done\r\n'
            '  timeout /t 1 /nobreak >nul\r\n'
            ')\r\n'
            'exit /b 1\r\n'
            ':done\r\n'
            'del /q "%SRC%" >nul 2>&1\r\n'
            'start "" "%DST%"\r\n'
            'del /q "%~f0" >nul 2>&1\r\n'
        )
        Path(bat).write_text(script,'utf-8')
        subprocess.Popen(['cmd','/c',bat],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        threading.Timer(0.5,lambda: os._exit(0)).start()
        return {'ok':True,'installing':True,'latest':latest}
    except Exception as e: return {'ok':False,'error':str(e)}

def chrome_login():
    PROFILE.mkdir(exist_ok=True)
    url=cfg().get('sheet_url') or 'https://docs.google.com/spreadsheets/'
    candidates=[os.path.expandvars(r'%PROGRAMFILES%\Google\Chrome\Application\chrome.exe'),os.path.expandvars(r'%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe'),os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe')]
    exe=next((x for x in candidates if os.path.exists(x)),None)
    if not exe: raise RuntimeError('Google Chrome을 찾을 수 없습니다.')
    subprocess.Popen([exe,f'--user-data-dir={PROFILE}',url])

def get_driver():
    global driver
    if driver:
        try: driver.title; return driver
        except: driver=None
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except Exception as e: raise RuntimeError('Selenium이 포함되지 않은 실행본입니다. 설치 패키지의 EXE를 사용해주세요.') from e
    o=Options(); o.add_argument(f'--user-data-dir={PROFILE}'); o.add_argument('--headless=new'); o.add_argument('--window-size=1600,1000'); o.add_argument('--disable-gpu'); o.add_argument('--no-first-run'); o.add_argument('--disable-dev-shm-usage')
    driver=webdriver.Chrome(options=o); return driver

def scrape_rows():
    c=cfg(); url=c.get('sheet_url','').strip()
    if not url: raise RuntimeError('Google Sheet URL이 설정되지 않았습니다.')
    d=get_driver(); d.get(url); time.sleep(3)
    # Google Sheets canvas/DOM variants: collect aria-labelled grid cells and map A-D by row/column metadata.
    js=r"""const out=[]; const els=[...document.querySelectorAll('[role="gridcell"], .waffle-cell')];
    for(const e of els){const r=e.getAttribute('aria-rowindex')||e.getAttribute('data-row'); const c=e.getAttribute('aria-colindex')||e.getAttribute('data-col');
      if(r&&c){out.push([+r,+c,(e.innerText||e.textContent||'').trim(),e.getAttribute('aria-checked')]);}}
    return out;"""
    cells=d.execute_script(js) or []
    rows={}
    for r,cx,txt,checked in cells:
        if r<4 or cx<1 or cx>4: continue
        rows.setdefault(str(r),{})[str(cx)] = ('TRUE' if checked=='true' else txt)
    result=[]
    for r,v in sorted(rows.items(),key=lambda x:int(x[0])):
        code=v.get('1','').strip(); name=v.get('2','').strip(); check=v.get('3','').strip(); when=v.get('4','').strip()
        if code or name: result.append({'row':int(r),'code':code,'name':name,'checked':check.lower() in ('true','1','yes','✓','☑') or bool(when),'when':when})
    if not result:
        raise RuntimeError('시트 행을 읽지 못했습니다. Google 로그인 버튼으로 로그인한 뒤 피킹문제보고 탭이 보이는지 확인해주세요.')
    return result

def add_alert(s,kind,row):
    a={'kind':kind,'code':row['code'],'name':row['name'],'when':row.get('when',''),'time':datetime.datetime.now().strftime('%m-%d %H:%M')}
    s['alerts']=[a]+s.get('alerts',[])[:99]

def check_once(notify=True):
    s=st()
    try:
        rows=scrape_rows(); old=s.get('rows',{}); new={}
        baseline=not bool(old)
        for r in rows:
            key=(r['code']+'|'+r['name']).strip('|') or 'row:'+str(r['row']); new[key]=r
            if baseline: continue
            if key not in old:
                add_alert(s,'new',r)
                if notify: slack(f"🟣 [신규 문제보고]\n상품코드: {r['code'] or '-'}\n상품명: {r['name'] or '-'}")
            elif r['checked'] and not old[key].get('checked'):
                add_alert(s,'resolved',r)
                if notify: slack(f"✅ [문제 해결됨]\n상품코드: {r['code'] or '-'}\n상품명: {r['name'] or '-'}\n확인 시점: {r.get('when') or '-'}")
        s['rows']=new; s['last_check']=datetime.datetime.now().isoformat(timespec='seconds'); s['last_error']=None; put_state(s); return {'ok':True,'count':len(rows),'baseline':baseline}
    except Exception as e:
        s['last_error']=str(e); put_state(s); return {'ok':False,'error':str(e)}

def monitor():
    while True:
        try:
            if effective_running(): check_once(True)
        except: pass
        time.sleep(max(10,int(cfg().get('interval',15))))

def local_ip():
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.connect(('8.8.8.8',80)); x=s.getsockname()[0]; s.close(); return x
    except:return '127.0.0.1'

class H(SimpleHTTPRequestHandler):
    def log_message(self,*a): pass
    def translate_path(self,path):
        p=urllib.parse.urlparse(path).path
        if p=='/':p='/index.html'
        return str(STATIC/p.lstrip('/'))
    def sendj(self,o,code=200):
        b=json.dumps(o,ensure_ascii=False).encode(); self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p=urllib.parse.urlparse(self.path)
        if p.path=='/api/state':
            c=cfg(); s=st(); safe={k:v for k,v in c.items() if k not in ('slack_token',)}; safe['slack_token_set']=bool(c.get('slack_token')); self.sendj({'config':safe,'state':s,'effective':effective_running(),'scheduled':scheduled(c),'version':VERSION,'mobile_url':f'http://{local_ip()}:8765/?token='+token()}); return
        if p.path.startswith('/api/') and not auth(self): self.sendj({'ok':False,'error':'unauthorized'},403); return
        super().do_GET()
    def do_POST(self):
        if not auth(self): self.sendj({'ok':False,'error':'unauthorized'},403); return
        n=int(self.headers.get('Content-Length','0')); data=json.loads(self.rfile.read(n) or b'{}'); p=urllib.parse.urlparse(self.path).path
        try:
            if p=='/api/save':
                c=cfg();
                for k in ('sheet_url','slack_user_id','interval','workdays','manual','update_manifest_url'):
                    if k in data:c[k]=data[k]
                if data.get('slack_token'): c['slack_token']=data['slack_token']
                save_json(SETTINGS,c); self.sendj({'ok':True}); return
            if p=='/api/toggle_day':
                c=cfg(); d=data['date']; c.setdefault('workdays',{})[d]=not c.get('workdays',{}).get(d,datetime.date.fromisoformat(d).weekday()<5); save_json(SETTINGS,c); self.sendj({'ok':True,'value':c['workdays'][d]}); return
            if p=='/api/manual':
                c=cfg(); c['manual']=data.get('value'); save_json(SETTINGS,c); self.sendj({'ok':True}); return
            if p=='/api/check': self.sendj(check_once(True)); return
            if p=='/api/update_check': self.sendj(check_update(bool(data.get('install')))); return
            if p=='/api/slack_test': slack('🟣 문제보고 알림 테스트\nSlack 연결이 정상입니다.'); self.sendj({'ok':True}); return
            if p=='/api/login': chrome_login(); self.sendj({'ok':True}); return
            self.sendj({'ok':False},404)
        except Exception as e:self.sendj({'ok':False,'error':str(e)},500)

def token():
    s=load_json(BASE/'token.json',{})
    if not s.get('token'):
        s={'token':hashlib.sha256(os.urandom(32)).hexdigest()[:32]}; save_json(BASE/'token.json',s)
    return s['token']
def auth(h):
    q=urllib.parse.parse_qs(urllib.parse.urlparse(h.path).query); return h.client_address[0] in ('127.0.0.1','::1') or q.get('token',[''])[0]==token() or h.headers.get('X-App-Token')==token()

def open_app():
    url='http://127.0.0.1:8765/'
    edge=os.path.expandvars(r'%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe')
    if not os.path.exists(edge): edge=os.path.expandvars(r'%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe')
    try: subprocess.Popen([edge,f'--app={url}','--start-maximized']) if os.path.exists(edge) else webbrowser.open(url)
    except:webbrowser.open(url)

def main():
    global server
    threading.Thread(target=monitor,daemon=True).start()
    server=ThreadingHTTPServer(('0.0.0.0',8765),H)
    threading.Timer(1,open_app).start()
    def auto_update():
        r=check_update(False)
        if r.get('ok') and r.get('update'):
            check_update(True)
    threading.Timer(5,auto_update).start()
    server.serve_forever()
if __name__=='__main__':main()
