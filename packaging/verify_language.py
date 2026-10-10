"""Check system locale and live language switching with temporary files in Chrome."""
import sys,os,json,subprocess,time,tempfile,re,signal
from pathlib import Path
from urllib.request import urlopen
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'packaging'))
from verify_browser import CDP
sys.path.insert(0,str(root));from editor import system_language
from unittest.mock import patch
for env,expected in [({'LANG':'ru_RU.UTF-8'},'ru'),({'LANG':'en_US.UTF-8'},'en'),({'LANG':'de_DE.UTF-8'},'en'),({'LANG':'C.UTF-8','LANGUAGE':'ru'},'en'),({'LANG':'en_US.UTF-8','LANGUAGE':'ru:en'},'ru'),({'LANG':'ru_RU.UTF-8','LC_ALL':'en_US.UTF-8'},'en'),({'LANG':'en_US.UTF-8','LC_MESSAGES':'ru_RU.UTF-8'},'ru')]:
 with patch.dict(os.environ,env,clear=True):assert system_language()==expected,(env,system_language())
print('System locale selection: OK',flush=True)
with tempfile.TemporaryDirectory(prefix='tablelens-language-') as td:
 folder=Path(td);chrome=subprocess.Popen(['/usr/bin/google-chrome-stable','--headless=new','--no-sandbox','--disable-dev-shm-usage','--remote-debugging-port=0','--user-data-dir='+str(folder/'profile'),'about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,start_new_session=True)
 try:
  portfile=folder/'profile'/'DevToolsActivePort'
  for _ in range(100):
   if portfile.exists():break
   if chrome.poll() is not None:raise RuntimeError(chrome.stderr.read().decode())
   time.sleep(.1)
  port=int(portfile.read_text().splitlines()[0]);targets=json.load(urlopen(f'http://127.0.0.1:{port}/json'));client=CDP(next(t['webSocketDebuggerUrl'] for t in targets if t['type']=='page'));client.call('Page.enable');client.call('Runtime.enable')
  for lang,expected in [('ru_RU.UTF-8','ru'),('en_US.UTF-8','en'),('fr_FR.UTF-8','en')]:
   env={**os.environ,'LANG':lang};[env.pop(k,None) for k in ['LANGUAGE','LC_ALL','LC_MESSAGES']]
   app=subprocess.Popen([sys.executable,'-B','editor.py','--no-browser','--storage-dir',str(folder/lang)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env,cwd=root)
   try:
    address=re.search(r'http://\S+',app.stdout.readline()).group(0);client.call('Page.navigate',{'url':address});client.wait("document.querySelector('#file-wizard')?.open")
    assert client.evaluate('document.documentElement.lang')==expected
    assert client.evaluate("$('wizard-language-toggle').textContent")==('En' if expected=='ru' else 'Рус')
    # Import without OS file chooser, then change column settings before switching.
    client.evaluate("(async()=>{showWizardConfig(await api('import',{name:'пример.tsv',content:btoa(unescape(encodeURIComponent('Имя\\tИсточник\\nСохранить\\thttps://example.org\\nВторая\\thttps://example.org')))}));})()")
    client.wait("!!wizardState&&$('wizard-columns').querySelectorAll('tbody tr').length===2")
    client.evaluate("$('wizard-columns').querySelector('.column-mode').value='read';$('wizard-columns').querySelector('.column-mode').onchange();$('wizard-columns').querySelector('.wizard-choices').value='Русский\\nEnglish';$('wizard-columns').querySelector('details').open=true;$('wizard-language-toggle').click()")
    assert client.evaluate('document.documentElement.lang')!=expected
    assert client.evaluate("$('wizard-columns').querySelector('.column-mode').value")=='read'
    assert client.evaluate("$('wizard-columns').querySelector('.wizard-choices').value")=='Русский\nEnglish'
    assert client.evaluate("$('wizard-columns').querySelector('details').open")
    assert client.evaluate("$('wizard-columns').querySelector('tbody td').firstChild.textContent")=='Имя'
    client.evaluate("$('wizard-language-toggle').click();$('wizard-columns').querySelector('.column-mode').value='edit';$('wizard-columns').querySelector('.column-mode').onchange();$('wizard-columns').querySelector('.wizard-choices').value='';$('auto').checked=false;$('wizard-start').click()")
    client.wait("!!state&&!$('file-wizard').open&&!busy&&!wizardBusy")
    client.evaluate("setEditorText($('col-0'),'Сохранить; drafted\\ntext');$('col-0').dispatchEvent(new Event('input'));$('jump').value='2';$('language-toggle').click()")
    assert client.evaluate('dirty()')
    assert client.evaluate('values()[0]')=='Сохранить; drafted\ntext'
    assert client.evaluate("$('jump').value")=='2'
    assert client.evaluate('state.index')==0
    assert client.evaluate("$('language-toggle').textContent")==('Рус' if expected=='ru' else 'En')
    client.evaluate("$('language-toggle').click()")
    assert client.evaluate('values()[0]')=='Сохранить; drafted\ntext'
    assert client.evaluate('document.documentElement.lang')==expected
    # Force English to check UI and server errors.
    client.evaluate("if(language!=='en')switchLanguage()")
    assert client.evaluate("$('settings').textContent")=='Columns'
    assert client.evaluate("$('shutdown').title")=='Stop the application and close the editor.'
    assert client.evaluate("t('В выбранном листе нет данных.')")=='The selected sheet contains no data.'
    assert client.evaluate("$('skipped-summary').textContent")=='Skipped (0)'
    assert client.evaluate("document.querySelector('#fields label').textContent")=='Имя'
    print(lang+': startup, toggle, wizard settings, drafts, user text, tooltips OK',flush=True)
   finally:app.terminate();app.wait(timeout=10)
 finally:
  if chrome.poll() is None:os.killpg(chrome.pid,signal.SIGTERM)
  chrome.wait(timeout=10)
