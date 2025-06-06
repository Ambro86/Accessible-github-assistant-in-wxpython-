#To create an executable use pyinstaller --onefile --windowed --add-data "locales;locales" --name AssistenteGit assistente-git.py
import wx
import os, time, platform
import subprocess
import fnmatch # Per il filtraggio dei file
import re # Aggiunto per regex nella gestione errori push
import json # Per gestire risposte API GitHub e config
import requests # Per chiamate API GitHub
import zipfile # Per gestire archivi ZIP dei log
import io # Per gestire stream di byte in memoria
import struct # Per il formato archivio personalizzato
import gzip # Per comprimere i dati prima della crittografia
import uuid # Per l'identificatore univoco dell'utente
import base64 # Per la chiave Fernet
import webbrowser
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from cryptography.fernet import Fernet, InvalidToken # Per la crittografia
from datetime import datetime, timezone # Aggiungi timezone da datetime
# --- Setup gettext for internationalization ---
import gettext
import locale

print("DEBUG: Starting gettext setup...")
try:
    locale.setlocale(locale.LC_ALL, '')
    current_locale_info = locale.getlocale()
    print(f"DEBUG: Locale dopo setlocale(locale.LC_ALL, ''): {current_locale_info}")
except locale.Error as e:
    print(f"DEBUG: Errore nell'impostare la locale con stringa vuota: {e}")
    current_locale_info = (None, None)

lang_code = None
languages = ['en']

try:
    lang_code = current_locale_info[0]
    print(f"DEBUG: Codice lingua iniziale rilevato: '{lang_code}' (tipo: {type(lang_code)})")
    if lang_code and lang_code.strip():
        processed_languages = []
        if os.name == 'nt': # Windows specific handling
            lang_lower = lang_code.lower()
            if lang_lower.startswith('italian'): processed_languages = ['it_IT', 'it']
            elif lang_lower.startswith('english'): processed_languages = ['en_US', 'en']
            elif lang_lower.startswith('french'): processed_languages = ['fr_FR', 'fr']
            elif lang_lower.startswith('german'): processed_languages = ['de_DE', 'de']
            elif lang_lower.startswith('russian'): processed_languages = ['ru_RU', 'ru']
            elif lang_lower.startswith('portuguese'): processed_languages = ['pt_BR', 'pt']

        if not processed_languages:
            if '_' in lang_code:
                processed_languages.append(lang_code)
                short_code = lang_code.split('_')[0]
                if short_code not in processed_languages: processed_languages.append(short_code)
            elif lang_code:
                processed_languages.append(lang_code)

        if processed_languages and any(pl and pl.strip() for pl in processed_languages):
            languages = [pl for pl in processed_languages if pl and pl.strip()]
        else:
            print(f"DEBUG: Nessun codice lingua valido dopo l'elaborazione di '{lang_code}', fallback a inglese.")
            languages = ['en']
        print(f"DEBUG: Lista 'languages' finale per gettext: {languages}")
    else:
        print(f"DEBUG: lang_code era None o vuoto ('{lang_code}'), fallback a inglese.")
        languages = ['en']
except Exception as e_detect:
    print(f"DEBUG: ECCEZIONE durante il rilevamento/elaborazione della lingua: {type(e_detect).__name__}: {e_detect}")
    languages = ['en']

try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
except NameError:
    import sys
    script_dir = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, 'frozen', False) else os.getcwd()

localedir = os.path.join(script_dir, 'locales')
print(f"DEBUG: Directory 'locales' impostata a: {localedir}")
print(f"DEBUG: Tentativo di caricare traduzioni per le lingue: {languages} dal dominio 'assistente_git'")
try:
    lang_translations = gettext.translation('assistente_git', localedir=localedir, languages=languages, fallback=True)
except Exception as e_trans:
    print(f"DEBUG: ECCEZIONE durante gettext.translation: {type(e_trans).__name__}: {e_trans}")
    lang_translations = gettext.NullTranslations()
_ = lang_translations.gettext
print(f"DEBUG: Test translation for 'Pronto.': {_('Pronto.')}")
print(f"DEBUG: Type of lang_translations: {type(lang_translations)}")
# --- End setup gettext ---


# --- Costanti per l'archivio di configurazione ---
APP_CONFIG_DIR_NAME = "AssistenteGit"
USER_ID_FILE_NAME = "user_id.cfg"
SECURE_CONFIG_FILE_NAME = "github_settings.agd"
APP_SETTINGS_FILE_NAME = "settings.json" # Nuovo file per opzioni non sensibili
CONFIG_MAGIC_NUMBER_PREFIX = b'AGCF'
CONFIG_FORMAT_VERSION = 2
SALT_SIZE = 16
PBKDF2_ITERATIONS = 390000

# --- Define translatable command and category names (keys) ---
CAT_REPO_OPS = _("Operazioni di Base sul Repository")
CAT_LOCAL_CHANGES = _("Modifiche Locali e Commit")
CAT_BRANCH_TAG = _("Branch e Tag")
CAT_REMOTE_OPS = _("Operazioni con Repository Remoti")
CAT_STASH = _("Salvataggio Temporaneo (Stash)")
CAT_SEARCH_UTIL = _("Ricerca e Utilità")
CAT_RESTORE_RESET = _("Ripristino e Reset (Usare con Cautela!)")
CAT_GITHUB_ACTIONS = _("GitHub Actions")
CAT_GITHUB_PR_ISSUES = _("Pull Request e Issue")
CMD_CLONE = _("Clona un repository (nella cartella corrente)")
CMD_INIT_REPO = _("Inizializza un nuovo repository qui")
CMD_ADD_TO_GITIGNORE = _("Aggiungi cartella/file da ignorare a .gitignore")
CMD_STATUS = _("Controlla lo stato del repository")
CMD_DIFF = _("Visualizza modifiche non in stage (diff)")
CMD_DIFF_STAGED = _("Visualizza modifiche in stage (diff --staged)")
CMD_ADD_ALL = _("Aggiungi tutte le modifiche all'area di stage")
CMD_COMMIT = _("Crea un commit (salva modifiche)")
CMD_AMEND_COMMIT = _("Rinomina ultimo commit (amend)")
CMD_SHOW_COMMIT = _("Mostra dettagli di un commit specifico")
CMD_LOG_CUSTOM = _("Visualizza cronologia commit (numero personalizzato)")
CMD_GREP = _("Cerca testo nei file (git grep)")
CMD_LS_FILES = _("Cerca file nel progetto (tracciati da Git)")
CMD_TAG_LIGHTWEIGHT = _("Crea nuovo Tag (leggero)")
CMD_FETCH_ORIGIN = _("Scarica da remoto 'origin' (fetch)")
CMD_PULL = _("Scarica le modifiche dal server e unisci (pull)")
CMD_PUSH = _("Invia le modifiche al server (push)")
CMD_REMOTE_ADD_ORIGIN = _("Aggiungi repository remoto 'origin'")
CMD_REMOTE_SET_URL = _("Modifica URL del repository remoto 'origin'")
CMD_REMOTE_V = _("Controlla indirizzi remoti configurati")
CMD_BRANCH_A = _("Visualizza tutti i branch (locali e remoti)")
CMD_BRANCH_SHOW_CURRENT = _("Controlla branch corrente")
CMD_BRANCH_NEW_NO_SWITCH = _("Crea nuovo branch (senza cambiare)")
CMD_CHECKOUT_B = _("Crea e passa a un nuovo branch")
CMD_CHECKOUT_EXISTING = _("Passa a un branch esistente")
CMD_MERGE = _("Unisci branch specificato nel corrente (merge)")
CMD_MERGE_ABORT = _("Annulla tentativo di merge (abort)")
CMD_BRANCH_D = _("Elimina branch locale (sicuro, -d)")
CMD_BRANCH_FORCE_D = _("Elimina branch locale (forzato, -D)")
CMD_PUSH_DELETE_BRANCH = _("Elimina branch remoto ('origin')")
CMD_STASH_SAVE = _("Salva modifiche temporaneamente (stash)")
CMD_STASH_POP = _("Applica ultime modifiche da stash (stash pop)")
CMD_RESTORE_FILE = _("Annulla modifiche su file specifico (restore)")
CMD_CHECKOUT_COMMIT_CLEAN = _("Sovrascrivi file con commit e pulisci (checkout <commit> . && clean -fd)")
CMD_RESTORE_CLEAN = _("Ripristina file modificati e pulisci file non tracciati")
CMD_CHECKOUT_DETACHED = _("Ispeziona commit specifico (checkout - detached HEAD)")
CMD_RESET_TO_REMOTE = _("Resetta branch locale a versione remota (origin/nome-branch)")
CMD_RESET_HARD_COMMIT = _("Resetta branch corrente a commit specifico (reset --hard)")
CMD_RESET_HARD_HEAD = _("Annulla modifiche locali (reset --hard HEAD)")
CMD_GITHUB_CONFIGURE = _("Configura Repository GitHub & Opzioni")
CMD_GITHUB_SELECTED_RUN_LOGS = _("Visualizza log Workflow")
CMD_GITHUB_DOWNLOAD_SELECTED_ARTIFACT = _("Elenca e Scarica Artefatti Esecuzione Selezionata")
# --- NUOVO COMANDO PER CREAZIONE RELEASE ---
CMD_GITHUB_CREATE_RELEASE = _("Crea Nuova Release GitHub con Asset")
CMD_GITHUB_DELETE_RELEASE = _("Elimina Release GitHub (per ID o Tag)")
CMD_GITHUB_EDIT_RELEASE = _("Modifica Release GitHub Esistente")
CMD_GITHUB_TRIGGER_WORKFLOW = _("Trigger Workflow Manuale")
CMD_GITHUB_CANCEL_WORKFLOW = _("Cancella Workflow in Esecuzione")
CMD_GITHUB_CREATE_ISSUE = _("Crea Nuova Issue")
CMD_GITHUB_CREATE_PR = _("Crea Nuova Pull Request")
CMD_GITHUB_LIST_ISSUES = _("Visualizza Issue del Repository")
CMD_GITHUB_EDIT_ISSUE = _("Modifica Issue Esistente")
CMD_GITHUB_DELETE_ISSUE = _("Chiudi/Elimina Issue")
CMD_GITHUB_LIST_PRS = _("Visualizza Pull Request del Repository")
CMD_GITHUB_EDIT_PR = _("Modifica Pull Request Esistente")
CMD_GITHUB_DELETE_PR = _("Chiudi/Elimina Pull Request")
CAT_DASHBOARD = _("Dashboard Repository")
CMD_REPO_STATUS_OVERVIEW = _("Panoramica Stato Repository")
CMD_REPO_STATISTICS = _("Statistiche Repository")
CMD_RECENT_ACTIVITY = _("Attività Recente")
CMD_BRANCH_STATUS = _("Stato Branch e Remote")
CMD_FILE_CHANGES_SUMMARY = _("Riepilogo Modifiche File")

# --- FINE NUOVO COMANDO ---

# --- Finestra di Dialogo Personalizzata per l'Input ---
class InputDialog(wx.Dialog):
    def __init__(self, parent, title, prompt, placeholder=""):
        super(InputDialog, self).__init__(parent, title=title, size=(450, 150))
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        prompt_label = wx.StaticText(panel, label=prompt)
        main_sizer.Add(prompt_label, 0, wx.ALL | wx.EXPAND, 10)
        self.text_ctrl = wx.TextCtrl(panel, value=placeholder)
        main_sizer.Add(self.text_ctrl, 0, wx.ALL | wx.EXPAND, 10)
        button_sizer = wx.StdDialogButtonSizer()
        ok_button = wx.Button(panel, wx.ID_OK)
        ok_button.SetDefault()
        button_sizer.AddButton(ok_button)
        cancel_button = wx.Button(panel, wx.ID_CANCEL)
        button_sizer.AddButton(cancel_button)
        button_sizer.Realize()
        main_sizer.Add(button_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        panel.SetSizer(main_sizer)
        self.text_ctrl.SetFocus()

    def GetValue(self):
        return self.text_ctrl.GetValue().strip()

# --- Finestra di Dialogo per Configurazione GitHub (MODIFICATA) ---
class GitHubConfigDialog(wx.Dialog):
    def __init__(self, parent, title, current_owner, current_repo,
                 current_token_present, current_ask_pass_on_startup, current_strip_timestamps, current_monitoring_beep):
        super(GitHubConfigDialog, self).__init__(parent, title=title)
        self.parent_frame = parent
        panel = wx.Panel(self)
        self.panel = panel # Salva riferimento al panel per UpdatePasswordControlsState
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        main_sizer.Add(wx.StaticText(panel, label=_("Configura i dettagli del repository GitHub e le opzioni.")), 0, wx.ALL | wx.EXPAND, 10)

        owner_label = wx.StaticText(panel, label=_("Proprietario (utente/organizzazione GitHub):"))
        self.owner_ctrl = wx.TextCtrl(panel, value=current_owner)
        main_sizer.Add(owner_label, 0, wx.LEFT|wx.RIGHT|wx.TOP, 10)
        main_sizer.Add(self.owner_ctrl, 0, wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, 5)

        repo_label = wx.StaticText(panel, label=_("Nome Repository GitHub:"))
        self.repo_ctrl = wx.TextCtrl(panel, value=current_repo)
        main_sizer.Add(repo_label, 0, wx.LEFT|wx.RIGHT|wx.TOP, 5)
        main_sizer.Add(self.repo_ctrl, 0, wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, 10)

        token_label_text = _("Personal Access Token (PAT) GitHub:")
        if current_token_present:
            token_label_text += _(" (Attualmente memorizzato. Inserisci per cambiare o lascia vuoto per tentare di rimuovere.)")
        else:
            token_label_text += _(" (Opzionale, ma consigliato per repository privati e operazioni complete. Supporta sia Fine-grained che Classic tokens.)")
        token_label = wx.StaticText(panel, label=token_label_text)
        self.token_ctrl = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
        main_sizer.Add(token_label, 0, wx.LEFT|wx.RIGHT|wx.TOP, 5)
        main_sizer.Add(self.token_ctrl, 0, wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, 10)

        self.password_label = wx.StaticText(panel, label=_("Password Master (per crittografare/decrittografare il token):"))
        self.password_ctrl = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
        main_sizer.Add(self.password_label, 0, wx.LEFT|wx.RIGHT|wx.TOP, 5)
        main_sizer.Add(self.password_ctrl, 0, wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, 5)

        self.password_explanation_text = wx.StaticText(panel, label="")
        main_sizer.Add(self.password_explanation_text, 0, wx.LEFT|wx.RIGHT|wx.BOTTOM, 10)

        self.ask_pass_startup_cb = wx.CheckBox(panel, label=_("Richiedi password master all'avvio per funzionalità GitHub"))
        self.ask_pass_startup_cb.SetValue(current_ask_pass_on_startup)
        self.ask_pass_startup_cb.Bind(wx.EVT_CHECKBOX, self.OnAskPassStartupChanged)
        main_sizer.Add(self.ask_pass_startup_cb, 0, wx.ALL, 10)

        self.strip_timestamps_cb = wx.CheckBox(panel, label=_("Rimuovi timestamp dai log di GitHub Actions"))
        self.strip_timestamps_cb.SetValue(current_strip_timestamps)
        main_sizer.Add(self.strip_timestamps_cb, 0, wx.LEFT|wx.RIGHT|wx.BOTTOM, 10)
        self.monitoring_beep_cb = wx.CheckBox(panel, label=_("Beep sonoro durante monitoraggio workflow"))
        self.monitoring_beep_cb.SetValue(current_monitoring_beep)
        main_sizer.Add(self.monitoring_beep_cb, 0, wx.LEFT|wx.RIGHT|wx.BOTTOM, 10)
        btn_panel = wx.Panel(panel)
        btn_sizer_h = wx.BoxSizer(wx.HORIZONTAL)
        self.delete_config_button = wx.Button(btn_panel, label=_("Elimina Configurazione Salvata"))
        self.create_token_button = wx.Button(btn_panel, label=_("Crea Token GitHub"))
        btn_sizer_h.Add(self.delete_config_button, 0, wx.RIGHT, 10)
        btn_sizer_h.Add(self.create_token_button, 0, wx.RIGHT, 20)
        std_button_sizer = wx.StdDialogButtonSizer()
        ok_button = wx.Button(btn_panel, wx.ID_OK, label=_("Salva Configurazione"))
        ok_button.SetDefault()
        std_button_sizer.AddButton(ok_button)
        cancel_button = wx.Button(btn_panel, wx.ID_CANCEL)
        std_button_sizer.AddButton(cancel_button)
        std_button_sizer.Realize()
        btn_sizer_h.Add(std_button_sizer, 0, wx.EXPAND)
        btn_panel.SetSizer(btn_sizer_h)
        main_sizer.Add(btn_panel, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        panel.SetSizer(main_sizer) # Il sizer è impostato per il panel

        self.owner_ctrl.SetFocus()
        self.delete_config_button.Bind(wx.EVT_BUTTON, self.OnDeleteConfig)
        self.create_token_button.Bind(wx.EVT_BUTTON, self.OnCreateToken)

        self.UpdatePasswordControlsState() # Chiama per impostare lo stato iniziale

        # CORREZIONE: Adatta la dimensione del dialogo al suo contenuto (il panel)
        # e centralo. Non è necessario self.Layout() qui se Fit() fa il suo lavoro.
        self.Fit()
        self.Centre()
    def OnAskPassStartupChanged(self, event):
        """Chiamato quando lo stato della checkbox 'ask_pass_startup_cb' cambia."""
        self.UpdatePasswordControlsState()
        event.Skip()

    def UpdatePasswordControlsState(self):
        """Aggiorna la visibilità e il testo dei controlli relativi alla password
           in base allo stato della checkbox 'ask_pass_startup_cb'."""
        ask_pass_is_checked = self.ask_pass_startup_cb.GetValue()

        self.password_label.Show(ask_pass_is_checked)
        self.password_ctrl.Show(ask_pass_is_checked)

        if ask_pass_is_checked:
            self.password_ctrl.SetHint(_("Obbligatoria se si inserisce/modifica il token"))
            self.password_explanation_text.SetLabel(
                _("La Password Master è OBBLIGATORIA qui se si inserisce o modifica il Token PAT.\n"
                  "Lasciare vuoto il Token PAT per non salvarlo o tentare di rimuoverlo.")
            )
        else:
            self.password_ctrl.SetValue("")
            self.password_ctrl.SetHint("")
            self.password_explanation_text.SetLabel(
                _("Poiché 'Richiedi password all'avvio' è disabilitato:\n"
                  "- Non verrà chiesta una Password Master all'avvio.\n"
                  "- Se inserisci un Token PAT qui sopra, sarà salvato usando una\n"
                  "  crittografia basata su una password vuota (operazione meno sicura).")
            )

        # CORREZIONE: Riorganizza il layout del panel e poi adatta la dimensione del dialogo.
        if self.panel: # Assicurati che self.panel esista
            self.panel.Layout()  # Ricalcola il layout del pannello
        self.Fit()           # Adatta la dimensione del dialogo al suo contenuto aggiornato
        # self.Layout() # Di solito non necessario dopo Fit() sul dialogo stesso
        self.Refresh()       # Forza un ridisegno per assicurare che le modifiche siano visibili
        
    def OnDeleteConfig(self, event):
        print("DEBUG: OnDeleteConfig chiamato") # Questo lo vedi già
        # Tentiamo di scrivere anche nell'output GUI per conferma
        if self.parent_frame and hasattr(self.parent_frame, 'output_text_ctrl'):
            self.parent_frame.output_text_ctrl.AppendText("DEBUG: OnDeleteConfig invocato (GUI)\n")
        else:
            print("DEBUG: parent_frame o output_text_ctrl non disponibile per il messaggio di debug GUI iniziale.")

        risposta = wx.MessageBox(
            _("Sei sicuro di voler eliminare tutta la configurazione GitHub salvata (incluso il token)?\n"
              "Questa azione è irreversibile."),
            _("Conferma Eliminazione Configurazione"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
            self  # self è GitHubConfigDialog, il genitore del MessageBox
        )
        # Output di debug aggiuntivi per analizzare 'risposta'
        print(f"DEBUG: wx.MessageBox ha restituito il valore: {risposta}")
        print(f"DEBUG: Il valore atteso per wx.ID_YES è: {wx.ID_YES}")
        print(f"DEBUG: Il valore atteso per wx.ID_NO è: {wx.ID_NO}")

        if not (risposta == wx.ID_YES or risposta == 2):
            print(f"DEBUG: La condizione 'risposta ({risposta}) non è né wx.ID_YES ({wx.ID_YES}) né 2' è VERA. L'utente NON ha premuto 'Sì' o il valore restituito è inatteso.")
            if self.parent_frame and hasattr(self.parent_frame, 'output_text_ctrl'):
                self.parent_frame.output_text_ctrl.AppendText(f"DEBUG: Eliminazione annullata dall'utente o risposta inattesa ({risposta}) da MessageBox.\n")
            return # Esce dal metodo se l'utente non ha premuto "Sì"

        # Se arriviamo qui, l'utente ha premuto "Sì"
        print(f"DEBUG: La condizione 'risposta ({risposta}) != wx.ID_YES ({wx.ID_YES})' è FALSA. L'utente HA premuto 'Sì'.")
        if self.parent_frame and hasattr(self.parent_frame, 'output_text_ctrl'):
            self.parent_frame.output_text_ctrl.AppendText("DEBUG: Utente ha confermato eliminazione, apro PasswordEntryDialog\n")
        else:
            print("DEBUG: parent_frame o output_text_ctrl non disponibile per il messaggio GUI 'apro PasswordEntryDialog'.")


        password_dialog = wx.PasswordEntryDialog(
            self, # self è GitHubConfigDialog, il genitore del PasswordEntryDialog
            _("Inserisci la Password Master per confermare l'eliminazione della configurazione "
              "(lascia vuoto se hai disabilitato 'Richiedi password all'avvio'):"),
            _("Conferma Password per Eliminazione")
        )

        if password_dialog.ShowModal() != wx.ID_OK:
            if self.parent_frame and hasattr(self.parent_frame, 'output_text_ctrl'):
                self.parent_frame.output_text_ctrl.AppendText("DEBUG: Utente ha chiuso PasswordEntryDialog senza confermare\n")
            else:
                print("DEBUG: Utente ha chiuso PasswordEntryDialog senza confermare (messaggio GUI non disponibile).")
            password_dialog.Destroy()
            return

        pw = password_dialog.GetValue()
        if self.parent_frame and hasattr(self.parent_frame, 'output_text_ctrl'):
            self.parent_frame.output_text_ctrl.AppendText(f"DEBUG: Password inserita: '{pw}'\n")
        print(f"DEBUG: Password inserita nel dialogo di eliminazione: '{pw}'") # Aggiunto anche a console per sicurezza
        password_dialog.Destroy()

        risultato = self.parent_frame._remove_github_config(pw)
        if risultato:
            wx.MessageBox(
                _("Configurazione GitHub eliminata con successo."),
                _("Configurazione Eliminata"),
                wx.OK | wx.ICON_INFORMATION,
                self
            )
            if self.parent_frame and hasattr(self.parent_frame, 'output_text_ctrl'):
                self.parent_frame.output_text_ctrl.AppendText("DEBUG: _remove_github_config ha restituito True\n")
            # Resetta i campi del dialogo
            self.owner_ctrl.SetValue("")
            self.repo_ctrl.SetValue("")
            self.token_ctrl.SetValue("")
            # Le impostazioni sottostanti nel frame genitore vengono resettate da _remove_github_config
            # self.parent_frame.github_ask_pass_on_startup = True
            # self.parent_frame.github_strip_log_timestamps = False
            # Aggiorniamo i checkbox nel dialogo per riflettere questi default
            self.ask_pass_startup_cb.SetValue(True)
            self.strip_timestamps_cb.SetValue(False)

            if self.parent_frame and hasattr(self.parent_frame, 'output_text_ctrl'):
                self.parent_frame.output_text_ctrl.AppendText("DEBUG: Campi dialogo resettati ai default dopo eliminazione.\n")
        else:
            # _remove_github_config dovrebbe mostrare il suo messaggio di errore se la password è errata etc.
            if self.parent_frame and hasattr(self.parent_frame, 'output_text_ctrl'):
                self.parent_frame.output_text_ctrl.AppendText("DEBUG: _remove_github_config ha restituito False\n")
            print("DEBUG: _remove_github_config ha restituito False (la funzione stessa dovrebbe aver mostrato un errore all'utente se necessario).")
    def GetValues(self):
        return {
            "owner": self.owner_ctrl.GetValue().strip(),
            "repo": self.repo_ctrl.GetValue().strip(),
            "token": self.token_ctrl.GetValue(),
            "password": self.password_ctrl.GetValue(),
            "ask_pass_on_startup": self.ask_pass_startup_cb.GetValue(),
            "strip_log_timestamps": self.strip_timestamps_cb.GetValue(),
            "monitoring_beep": self.monitoring_beep_cb.GetValue()
        }

    def OnCreateToken(self, event):
        """Apre la pagina GitHub per creare un nuovo token."""
        try:
            token_url = "https://github.com/settings/personal-access-tokens"
            webbrowser.open(token_url)
            
            info_msg = _(
                "Pagina GitHub aperta nel browser!\n\n"
                "📋 Istruzioni rapide:\n"
                "1. Clicca 'Generate new token'\n"
                "2. Scegli 'Fine-grained' (consigliato) o 'Classic'\n"
                "3. Inserisci descrizione e scadenza\n"
                "4. Seleziona permessi appropriati per il tuo repository\n"
                "5. Genera e copia subito il token\n"
                "6. Incolla il token nel campo sopra\n\n"
                "💡 Il token sarà visibile solo una volta!"
            )
            
            wx.MessageBox(info_msg, _("Token GitHub - Istruzioni"), wx.OK | wx.ICON_INFORMATION, self)
            
        except Exception as e:
            wx.MessageBox(
                _("Errore nell'aprire il browser.\n\n"
                  "Vai manualmente a:\n"
                  "https://github.com/settings/personal-access-tokens"),
                _("Errore Browser"), wx.OK | wx.ICON_ERROR, self
            )
            
class WorkflowInputDialog(wx.Dialog):
    def __init__(self, parent, title, workflow_name):
        super().__init__(parent, title=title, size=(500, 400))
        
        self.workflow_name = workflow_name
        self.inputs_data = {}
        
        self.create_ui()
        self.Center()
    
    def create_ui(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Titolo
        title_label = wx.StaticText(self, label=f"Trigger Workflow: {self.workflow_name}")
        title_font = title_label.GetFont()
        title_font.SetWeight(wx.FONTWEIGHT_BOLD)
        title_label.SetFont(title_font)
        main_sizer.Add(title_label, 0, wx.ALL|wx.CENTER, 10)
        
        # Branch selection
        branch_sizer = wx.BoxSizer(wx.HORIZONTAL)
        branch_label = wx.StaticText(self, label="Branch/Ref:")
        parent = self.GetParent()
        # Provo a risalire al percorso del repository: se esiste repo_path_ctrl, lo uso, altrimenti cwd
        if hasattr(parent, 'repo_path_ctrl') and parent.repo_path_ctrl:
            repo_path = parent.repo_path_ctrl.GetValue()
        else:
            repo_path = os.getcwd()

        branch_name = "main"
        if hasattr(parent, 'GetCurrentBranchName'):
            cb = parent.GetCurrentBranchName(repo_path)
            if cb: 
                branch_name = cb
        # -------------------------------------------------------------------
        self.branch_ctrl = wx.TextCtrl(self, value=branch_name, size=(200, -1))
        branch_sizer.Add(branch_label, 0, wx.ALL|wx.ALIGN_CENTER_VERTICAL, 5)
        branch_sizer.Add(self.branch_ctrl, 1, wx.ALL|wx.EXPAND, 5)
        main_sizer.Add(branch_sizer, 0, wx.ALL|wx.EXPAND, 5)
        
        # Inputs section
        inputs_label = wx.StaticText(self, label="Input Parameters (JSON format):")
        main_sizer.Add(inputs_label, 0, wx.ALL, 5)
        
        self.inputs_ctrl = wx.TextCtrl(self, 
                                       style=wx.TE_MULTILINE,
                                       size=(-1, 150),
                                       value='{}')
        main_sizer.Add(self.inputs_ctrl, 1, wx.ALL|wx.EXPAND, 5)
        
        # Help text
        help_text = wx.StaticText(self, 
                                  label="💡 Tip: Lascia vuoto {} se il workflow non richiede input")
        help_text.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_ITALIC, wx.FONTWEIGHT_NORMAL))
        main_sizer.Add(help_text, 0, wx.ALL, 5)
        
        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.validate_btn = wx.Button(self, label="Valida JSON")
        self.trigger_btn = wx.Button(self, wx.ID_OK, "Trigger Workflow")
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "Annulla")
        
        button_sizer.Add(self.validate_btn, 0, wx.ALL, 5)
        button_sizer.AddStretchSpacer()
        button_sizer.Add(self.trigger_btn, 0, wx.ALL, 5)
        button_sizer.Add(cancel_btn, 0, wx.ALL, 5)
        
        main_sizer.Add(button_sizer, 0, wx.ALL|wx.EXPAND, 10)
        
        # Bind events
        self.Bind(wx.EVT_BUTTON, self.OnValidateJSON, self.validate_btn)
        self.Bind(wx.EVT_BUTTON, self.OnOK, self.trigger_btn)
        
        self.SetSizer(main_sizer)
    
    def OnValidateJSON(self, event):
        """Valida il JSON degli input."""
        try:
            json_text = self.inputs_ctrl.GetValue().strip()
            if not json_text or json_text == "{}":
                wx.MessageBox("JSON vuoto - OK per workflow senza input", "Validazione", wx.OK | wx.ICON_INFORMATION)
                return
            
            parsed = json.loads(json_text)
            wx.MessageBox(f"✅ JSON valido!\nParsed: {len(parsed)} parametri", "Validazione", wx.OK | wx.ICON_INFORMATION)
        except json.JSONDecodeError as e:
            wx.MessageBox(f"❌ JSON non valido:\n{e}", "Errore Validazione", wx.OK | wx.ICON_ERROR)
        except Exception as e:
            wx.MessageBox(f"❌ Errore imprevisto:\n{e}", "Errore", wx.OK | wx.ICON_ERROR)
    
    def OnOK(self, event):
        """Valida e chiude il dialog."""
        branch = self.branch_ctrl.GetValue().strip()
        if not branch:
            wx.MessageBox("Il branch/ref è obbligatorio", "Errore", wx.OK | wx.ICON_ERROR)
            return
        
        # Valida JSON
        try:
            json_text = self.inputs_ctrl.GetValue().strip()
            if json_text and json_text != "{}":
                self.inputs_data = json.loads(json_text)
            else:
                self.inputs_data = {}
        except json.JSONDecodeError as e:
            wx.MessageBox(f"JSON non valido:\n{e}", "Errore", wx.OK | wx.ICON_ERROR)
            return
        
        self.EndModal(wx.ID_OK)
    
    def GetValues(self):
        """Restituisce i valori inseriti."""
        return {
            'branch': self.branch_ctrl.GetValue().strip(),
            'inputs': self.inputs_data
        }

# --- NUOVA FINESTRA DI DIALOGO PER CREAZIONE RELEASE ---
class CreateReleaseDialog(wx.Dialog):
    def __init__(self, parent, title):
        super(CreateReleaseDialog, self).__init__(parent, title=title, size=(650, 600)) # Aumentata dimensione
        self.panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Input Sizer (Tag, Titolo, Descrizione)
        input_grid_sizer = wx.FlexGridSizer(cols=2, gap=(5, 5))
        input_grid_sizer.AddGrowableCol(1, 1)

        # 1) Tag della release
        tag_label = wx.StaticText(self.panel, label=_("Tag della Release (es: v1.0.0):"))
        self.tag_ctrl = wx.TextCtrl(self.panel)
        input_grid_sizer.Add(tag_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        input_grid_sizer.Add(self.tag_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        # 2) Titolo della release
        title_label = wx.StaticText(self.panel, label=_("Titolo della Release:"))
        self.title_ctrl = wx.TextCtrl(self.panel)
        input_grid_sizer.Add(title_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        input_grid_sizer.Add(self.title_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        # 3) Descrizione della release
        desc_label = wx.StaticText(self.panel, label=_("Descrizione della Release (breve):"))
        self.desc_ctrl = wx.TextCtrl(self.panel, style=wx.TE_MULTILINE, size=(-1, 100))
        input_grid_sizer.Add(desc_label, 0, wx.ALIGN_TOP | wx.ALL, 5) # Align top for multiline
        input_grid_sizer.Add(self.desc_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        main_sizer.Add(input_grid_sizer, 0, wx.EXPAND | wx.ALL, 10)

        # 4) Selezione Asset
        assets_box = wx.StaticBox(self.panel, label=_("Asset da Caricare (Opzionale)"))
        assets_sizer = wx.StaticBoxSizer(assets_box, wx.VERTICAL)

        self.assets_list_ctrl = wx.ListBox(self.panel, style=wx.LB_SINGLE, size=(-1, 150))
        assets_sizer.Add(self.assets_list_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        asset_buttons_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.add_asset_button = wx.Button(self.panel, label=_("Aggiungi File..."))
        self.remove_asset_button = wx.Button(self.panel, label=_("Rimuovi Selezionato"))
        self.clear_assets_button = wx.Button(self.panel, label=_("Rimuovi Tutti"))

        asset_buttons_sizer.Add(self.add_asset_button, 0, wx.ALL, 5)
        asset_buttons_sizer.Add(self.remove_asset_button, 0, wx.ALL, 5)
        asset_buttons_sizer.Add(self.clear_assets_button, 0, wx.ALL, 5)
        assets_sizer.Add(asset_buttons_sizer, 0, wx.ALIGN_CENTER | wx.BOTTOM, 5)

        main_sizer.Add(assets_sizer, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Pulsanti OK / Cancel
        button_sizer = wx.StdDialogButtonSizer()
        self.ok_button = wx.Button(self.panel, wx.ID_OK, label=_("Crea Release"))
        self.ok_button.SetDefault()
        button_sizer.AddButton(self.ok_button)
        self.cancel_button = wx.Button(self.panel, wx.ID_CANCEL)
        button_sizer.AddButton(self.cancel_button)
        button_sizer.Realize()
        main_sizer.Add(button_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        self.panel.SetSizer(main_sizer)
        self.tag_ctrl.SetFocus()

        # Bind events
        self.add_asset_button.Bind(wx.EVT_BUTTON, self.OnAddAssets)
        self.remove_asset_button.Bind(wx.EVT_BUTTON, self.OnRemoveAsset)
        self.clear_assets_button.Bind(wx.EVT_BUTTON, self.OnClearAssets)
        # Bind OK button to perform validation before allowing dialog to close with wx.ID_OK
        self.ok_button.Bind(wx.EVT_BUTTON, self.OnOk)


        self.assets_paths = [] # Lista per memorizzare i percorsi completi dei file asset

    def OnOk(self, event):
        tag_name = self.tag_ctrl.GetValue().strip()
        release_name = self.title_ctrl.GetValue().strip()

        if not tag_name:
            wx.MessageBox(_("Il Tag della Release è obbligatorio."), _("Input Mancante"), wx.OK | wx.ICON_ERROR, self)
            self.tag_ctrl.SetFocus()
            return # Non chiudere il dialogo
        if not release_name:
            wx.MessageBox(_("Il Titolo della Release è obbligatorio."), _("Input Mancante"), wx.OK | wx.ICON_ERROR, self)
            self.title_ctrl.SetFocus()
            return # Non chiudere il dialogo
        
        self.EndModal(wx.ID_OK) # Chiudi il dialogo con successo


    def OnAddAssets(self, event):
        file_dlg = wx.FileDialog(
            self,
            _("Seleziona file da includere come asset (Ctrl/Cmd per selezionare multipli)"),
            wildcard=_("Tutti i file (*.*)|*.*"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE
        )
        if file_dlg.ShowModal() == wx.ID_OK:
            paths = file_dlg.GetPaths()
            for path in paths:
                if path not in self.assets_paths:
                    self.assets_paths.append(path)
                    self.assets_list_ctrl.Append(os.path.basename(path))
        file_dlg.Destroy()

    def OnRemoveAsset(self, event):
        selected_indices = self.assets_list_ctrl.GetSelections()
        # Rimuovi in ordine inverso per evitare problemi con gli indici
        for index in sorted(selected_indices, reverse=True):
            del self.assets_paths[index]
            self.assets_list_ctrl.Delete(index)

    def OnClearAssets(self, event):
        if not self.assets_paths:
            return
            
        confirm_dlg = wx.MessageDialog(
            self,
            _("Sei sicuro di voler rimuovere tutti gli asset dalla lista?"),
            _("Conferma Rimozione"),
            wx.YES_NO | wx.ICON_QUESTION
        )
        
        if confirm_dlg.ShowModal() == wx.ID_YES:
            self.assets_paths.clear()
            self.assets_list_ctrl.Clear()
        
        confirm_dlg.Destroy()
    def GetValues(self):
        return {
            "tag_name": self.tag_ctrl.GetValue().strip(),
            "release_name": self.title_ctrl.GetValue().strip(),
            "release_body": self.desc_ctrl.GetValue().strip(),
            "files_to_upload": self.assets_paths
        }
# --- FINE NUOVA FINESTRA DI DIALOGO ---

# --- Definizione Comandi ---
ORIGINAL_COMMANDS = {
    CMD_CLONE: {"type": "git", "cmds": [["git", "clone", "{input_val}"]], "input_needed": True, "input_label": _("URL del Repository da clonare:"), "placeholder": "https://github.com/utente/repo.git", "info": _("Clona un repository remoto specificato dall'URL...")},
    CMD_INIT_REPO: {"type": "git", "cmds": [["git", "init"]], "input_needed": False, "info": _("Crea un nuovo repository Git vuoto...")},
    CMD_ADD_TO_GITIGNORE: {"type": "git", "cmds": [], "input_needed": True, "input_label": "", "placeholder": "", "info": _("Permette di selezionare una cartella o un file da aggiungere al file .gitignore...")},
    CMD_STATUS: {"type": "git", "cmds": [["git", "status"]], "input_needed": False, "info": _("Mostra lo stato attuale della directory di lavoro...")},
    CMD_DIFF: {"type": "git", "cmds": [["git", "diff"]], "input_needed": False, "info": _("Mostra le modifiche apportate ai file tracciati...")},
    CMD_DIFF_STAGED: {"type": "git", "cmds": [["git", "diff", "--staged"]], "input_needed": False, "info": _("Mostra le modifiche che sono state aggiunte all'area di stage...")},
    CMD_ADD_ALL: {"type": "git", "cmds": [["git", "add", "."]], "input_needed": False, "info": _("Aggiunge tutte le modifiche correnti...")},
    CMD_COMMIT: {"type": "git", "cmds": [["git", "commit", "-m", "{input_val}"]], "input_needed": True, "input_label": _("Messaggio di Commit:"), "placeholder": "", "info": _("Salva istantanea delle modifiche...")},
    CMD_AMEND_COMMIT: {"type": "git", "cmds": [["git", "commit", "--amend", "-m", "{input_val}"]], "input_needed": True, "input_label": _("Nuovo messaggio per l'ultimo commit:"), "placeholder": _("Messaggio corretto del commit"), "info": _("Modifica il messaggio e/o i file dell'ultimo commit...")},
    CMD_SHOW_COMMIT: {"type": "git", "cmds": [["git", "show", "{input_val}"]], "input_needed": True, "input_label": _("Hash, tag o riferimento del commit (es. HEAD~2):"), "placeholder": _("es. a1b2c3d o HEAD"), "info": _("Mostra informazioni dettagliate su un commit specifico...")},
    CMD_LOG_CUSTOM: {"type": "git", "cmds": [["git", "log", "--oneline", "--graph", "--decorate", "--all", "-n", "{input_val}"]], "input_needed": True, "input_label": _("Quanti commit vuoi visualizzare? (numero):"), "placeholder": "20", "info": _("Mostra la cronologia dei commit...")},
    CMD_GREP: {"type": "git", "cmds": [["git", "grep", "-n", "-i", "{input_val}"]], "input_needed": True, "input_label": _("Testo da cercare nei file del repository:"), "placeholder": _("la mia stringa di ricerca"), "info": _("Cerca un pattern di testo...")},
    CMD_LS_FILES: {"type": "git", "cmds": [["git", "ls-files"]], "input_needed": True, "input_label": _("Pattern nome file (opzionale, es: *.py o parte del nome):"), "placeholder": _("*.py (lascia vuoto per tutti)"), "info": _("Elenca i file tracciati da Git...")},
    CMD_TAG_LIGHTWEIGHT: {"type": "git", "cmds": [["git", "tag"]], "input_needed": True, "input_label": _("Nome Tag [opz: HashCommit/Rif] (es: v1.0 o v1.0 a1b2c3d):"), "placeholder": _("v1.0 (per HEAD) oppure v1.0 a1b2c3d"), "info": _("Crea un tag leggero...")},
    CMD_FETCH_ORIGIN: {"type": "git", "cmds": [["git", "fetch", "origin"]], "input_needed": False, "info": _("Scarica tutte le novità...") },
    CMD_PULL: {"type": "git", "cmds": [["git", "pull"]], "input_needed": False, "info": _("Equivalente a un 'git fetch' seguito da un 'git merge'...") },
    CMD_PUSH: {"type": "git", "cmds": [["git", "push"]], "input_needed": False, "info": _("Invia i commit del tuo branch locale...") },
    CMD_REMOTE_ADD_ORIGIN: {"type": "git", "cmds": [["git", "remote", "add", "origin", "{input_val}"]], "input_needed": True, "input_label": _("URL del repository remoto (origin):"), "placeholder": "https://github.com/utente/repo.git", "info": _("Collega il tuo repository locale...") },
    CMD_REMOTE_SET_URL: {"type": "git", "cmds": [["git", "remote", "set-url", "origin", "{input_val}"]], "input_needed": True, "input_label": _("Nuovo URL del repository remoto (origin):"), "placeholder": "https://nuovo.server.com/utente/repo.git", "info": _("Modifica l'URL di un repository remoto esistente.") },
    CMD_REMOTE_V: {"type": "git", "cmds": [["git", "remote", "-v"]], "input_needed": False, "info": _("Mostra l'elenco dei repository remoti configurati.") },
    CMD_BRANCH_A: {"type": "git", "cmds": [["git", "branch", "-a"]], "input_needed": False, "info": _("Elenca tutti i branch locali e remoti...") },
    CMD_BRANCH_SHOW_CURRENT: {"type": "git", "cmds": [["git", "branch", "--show-current"]], "input_needed": False, "info": _("Mostra il nome del branch Git...") },
    CMD_BRANCH_NEW_NO_SWITCH: {"type": "git", "cmds": [["git", "branch", "{input_val}"]], "input_needed": True, "input_label": _("Nome del nuovo branch da creare:"), "placeholder": _("nuovo-branch-locale"), "info": _("Crea un nuovo branch locale...") },
    CMD_CHECKOUT_B: {"type": "git", "cmds": [["git", "checkout", "-b", "{input_val}"]], "input_needed": True, "input_label": _("Nome del nuovo branch da creare e a cui passare:"), "placeholder": _("feature/nome-branch"), "info": _("Crea un nuovo branch locale e ti sposta...") },
    CMD_CHECKOUT_EXISTING: {"type": "git", "cmds": [["git", "checkout", "{input_val}"]], "input_needed": True, "input_label": _("Nome del branch a cui passare:"), "placeholder": _("main"), "info": _("Ti sposta su un altro branch locale esistente.") },
    CMD_MERGE: {"type": "git", "cmds": [["git", "merge", "{input_val}"]], "input_needed": True, "input_label": _("Nome del branch da unire in quello corrente:"), "placeholder": _("feature/branch-da-unire"), "info": _("Integra le modifiche da un altro branch...") },
    CMD_MERGE_ABORT: {"type": "git", "cmds": [["git", "merge", "--abort"]], "input_needed": False, "info": _("Annulla un tentativo di merge fallito..."), "confirm": _("Sei sicuro di voler annullare il merge corrente e scartare le modifiche del tentativo di merge?")},
    CMD_BRANCH_D: {"type": "git", "cmds": [["git", "branch", "-d", "{input_val}"]], "input_needed": True, "input_label": _("Nome del branch locale da eliminare (sicuro):"), "placeholder": _("feature/vecchio-branch"), "info": _("Elimina un branch locale solo se è stato completamente unito..."), "confirm": _("Sei sicuro di voler tentare di eliminare il branch locale '{input_val}'?") },
    CMD_BRANCH_FORCE_D: {"type": "git", "cmds": [["git", "branch", "-D", "{input_val}"]], "input_needed": True, "input_label": _("Nome del branch locale da eliminare (FORZATO):"), "placeholder": _("feature/branch-da-forzare"), "info": _("ATTENZIONE: Elimina un branch locale forzatamente..."), "confirm": _("ATTENZIONE MASSIMA: Stai per eliminare forzatamente il branch locale '{input_val}'. Commit non mergiati verranno PERSI. Sei sicuro?") },
    CMD_PUSH_DELETE_BRANCH: {"type": "git", "cmds": [["git", "push", "origin", "--delete", "{input_val}"]], "input_needed": True, "input_label": _("Nome del branch su 'origin' da eliminare:"), "placeholder": _("feature/branch-remoto-obsoleto"), "info": _("Elimina un branch dal repository remoto 'origin'."), "confirm": _("Sei sicuro di voler eliminare il branch '{input_val}' dal remoto 'origin'?") },
    CMD_STASH_SAVE: {"type": "git", "cmds": [["git", "stash"]], "input_needed": False, "info": _("Mette da parte le modifiche non committate...") },
    CMD_STASH_POP: {"type": "git", "cmds": [["git", "stash", "pop"]], "input_needed": False, "info": _("Applica le modifiche dall'ultimo stash...") },
    CMD_RESTORE_FILE: {"type": "git", "cmds": [["git", "restore", "{input_val}"]], "input_needed": True, "input_label": "", "placeholder": "", "info": _("Annulla le modifiche non ancora in stage per un file specifico...") },
    CMD_CHECKOUT_COMMIT_CLEAN: {"type": "git", "cmds": [["git", "checkout", "{input_val}", "."], ["git", "clean", "-fd"]], "input_needed": True, "input_label": _("Hash/riferimento del commit da cui ripristinare i file:"), "placeholder": _("es. a1b2c3d o HEAD~1"), "info": _("ATTENZIONE: Sovrascrive i file con le versioni del commit..."), "confirm": _("Sei sicuro di voler sovrascrivere i file con le versioni del commit '{input_val}' E RIMUOVERE tutti i file/directory non tracciati?") },
    CMD_RESTORE_CLEAN: {"type": "git", "cmds": [["git", "restore", "."], ["git", "clean", "-fd"]], "input_needed": False, "confirm": _("ATTENZIONE: Ripristina file modificati E RIMUOVE file/directory non tracciati? Azione IRREVERSIBILE."), "info": _("Annulla modifiche nei file tracciati...") },
    CMD_CHECKOUT_DETACHED: {"type": "git", "cmds": [["git", "checkout", "{input_val}"]], "input_needed": True, "input_label": _("Hash/riferimento del commit da ispezionare:"), "placeholder": _("es. a1b2c3d o HEAD~3"), "info": _("Ti sposta su un commit specifico..."), "confirm": _("Stai per entrare in uno stato 'detached HEAD'. Nuove modifiche non apparterranno a nessun branch a meno che non ne crei uno. Continuare?") },
    CMD_RESET_TO_REMOTE: {"type": "git", "cmds": [ ["git", "fetch", "origin"], ["git", "reset", "--hard", "origin/{input_val}"] ], "input_needed": True, "input_label": _("Nome del branch remoto (es. main) a cui resettare:"), "placeholder": _("main"), "info": _("ATTENZIONE: Resetta il branch locale CORRENTE..."), "confirm": _("CONFERMA ESTREMA: Resettare il branch locale CORRENTE a 'origin/{input_val}'? TUTTI i commit locali non inviati e le modifiche non committate su questo branch verranno PERSI IRREVERSIBILMENTE. Sei sicuro?")},
    CMD_RESET_HARD_COMMIT: {"type": "git", "cmds": [["git", "reset", "--hard", "{input_val}"]], "input_needed": True, "input_label": _("Hash/riferimento del commit a cui resettare:"), "placeholder": _("es. a1b2c3d"), "info": _("ATTENZIONE MASSIMA: Sposta il puntatore del branch corrente..."), "confirm": _("CONFERMA ESTREMA: Stai per resettare il branch corrente a un commit precedente e PERDERE TUTTI i commit e le modifiche locali successive. Azione IRREVERSIBILE. Sei assolutamente sicuro?") },
    CMD_RESET_HARD_HEAD: {"type": "git", "cmds": [["git", "reset", "--hard", "HEAD"]], "input_needed": False, "confirm": _("ATTENZIONE: Annulla TUTTE le modifiche locali non committate e resetta all'ultimo commit?"), "info": _("Resetta il branch corrente all'ultimo commit...") },

    CMD_GITHUB_CONFIGURE: {"type": "github", "input_needed": False, "info": _("Imposta il repository GitHub (proprietario/repo), il Personal Access Token e le opzioni di caricamento/log.")},
    CMD_GITHUB_SELECTED_RUN_LOGS: {"type": "github", "input_needed": False, "info": _("Scarica e visualizza i log dell'esecuzione del workflow precedentemente selezionata.")},
    CMD_GITHUB_DOWNLOAD_SELECTED_ARTIFACT: {"type": "github", "input_needed": False, "info": _("Elenca gli artefatti dell'esecuzione del workflow selezionata e permette di scaricarli.")},
    CMD_GITHUB_CREATE_RELEASE: {"type": "github", "input_needed": False, "info": _("Crea una nuova release su GitHub, con opzione per caricare asset.")},
    CMD_GITHUB_DELETE_RELEASE: {
        "type": "github",
        "input_needed": False, # Non più input testuale diretto
        "info": _("Elenca le release esistenti su GitHub e permette di selezionarne una per l'eliminazione. L'eliminazione del tag Git associato è un'opzione aggiuntiva post-eliminazione della release."), # Info aggiornata
        # Il messaggio di conferma verrà formattato dinamicamente con il nome della release selezionata
        "confirm_template": _("ATTENZIONE: Stai per eliminare la release GitHub '{release_display_name}'. Questa azione è generalmente irreversibile sul sito di GitHub. Sei sicuro di voler procedere con l'eliminazione?")
    },
    CMD_GITHUB_EDIT_RELEASE: {
        "type": "github",
        "input_needed": False,
        "info": _("Modifica una release esistente: titolo, descrizione e aggiunta di nuovi asset. Permette di aggiornare i dettagli di una release già pubblicata su GitHub.")
    },
    CMD_GITHUB_TRIGGER_WORKFLOW: {
        "type": "github", 
        "input_needed": False, 
        "info": _("Avvia manualmente un workflow GitHub Actions dal repository configurato. Permette di selezionare il workflow e specificare parametri di input.")
    },
    CMD_GITHUB_CANCEL_WORKFLOW: {
        "type": "github", 
        "input_needed": False, 
        "info": _("Cancella un workflow GitHub Actions attualmente in esecuzione. Mostra una lista dei workflow in corso e permette di selezionarne uno da interrompere.")
    },

CMD_GITHUB_CREATE_ISSUE: {
    "type": "github", 
    "input_needed": False, 
    "info": _("Crea una nuova issue su GitHub con titolo, descrizione, labels e assignees. Supporta template predefiniti e assegnazione automatica di labels basate su priorità e tipo.")
},
CMD_GITHUB_CREATE_PR: {
    "type": "github", 
    "input_needed": False, 
    "info": _("Crea una nuova Pull Request su GitHub tra due branch. Permette di specificare titolo, descrizione, branch di origine e destinazione, con opzioni per draft e auto-merge.")
},
    CMD_GITHUB_LIST_ISSUES: {
        "type": "github", 
        "input_needed": False, 
        "info": _("Elenca le issue del repository con filtri per stato (aperte/chiuse), labels e assignees. Permette di visualizzare dettagli e selezionare issue per modifiche.")
    },
    CMD_GITHUB_EDIT_ISSUE: {
        "type": "github", 
        "input_needed": False, 
        "info": _("Modifica una issue esistente: titolo, descrizione, labels, assignees e stato. Permette di aggiornare completamente i dettagli di una issue selezionata.")
    },
    CMD_GITHUB_DELETE_ISSUE: {
        "type": "github", 
        "input_needed": False, 
        "info": _("Chiude una issue esistente. Le issue non possono essere eliminate completamente da GitHub, ma possono essere chiuse definitivamente.")
    },
    CMD_GITHUB_LIST_PRS: {
        "type": "github", 
        "input_needed": False, 
        "info": _("Elenca le Pull Request del repository con filtri per stato, branch e reviewer. Permette di visualizzare dettagli e selezionare PR per modifiche.")
    },
    CMD_GITHUB_EDIT_PR: {
        "type": "github", 
        "input_needed": False, 
        "info": _("Modifica una Pull Request esistente: titolo, descrizione, branch di destinazione, reviewers e stato draft. Permette aggiornamento completo dei dettagli.")
    },
    CMD_GITHUB_DELETE_PR: {
        "type": "github", 
        "input_needed": False, 
        "info": _("Chiude una Pull Request esistente. Le PR possono essere chiuse senza merge o forzatamente chiuse anche se non mergeabili.")
    },
    CMD_REPO_STATUS_OVERVIEW: {
        "type": "dashboard", 
        "input_needed": False, 
        "info": _("Mostra una panoramica completa dello stato del repository: branch corrente, modifiche pending, stato sync con remote, e statistiche generali.")
    },
    CMD_REPO_STATISTICS: {
        "type": "dashboard", 
        "input_needed": False, 
        "info": _("Visualizza statistiche dettagliate: numero di commit, contributori, dimensione repository, file più modificati, e trend temporali.")
    },
    CMD_RECENT_ACTIVITY: {
        "type": "dashboard", 
        "input_needed": False, 
        "info": _("Mostra gli ultimi 20 commit con informazioni dettagliate: autore, data, messaggi, e file modificati.")
    },
    CMD_BRANCH_STATUS: {
        "type": "dashboard", 
        "input_needed": False, 
        "info": _("Analisi dettagliata di tutti i branch: stato sync con remote, commit ahead/behind, ultimo commit, e suggerimenti per cleanup.")
    },
    CMD_FILE_CHANGES_SUMMARY: {
        "type": "dashboard", 
        "input_needed": False, 
        "info": _("Riepilogo delle modifiche correnti: file modificati, aggiunti, eliminati, con preview delle differenze e statistiche.")
    },
}
CATEGORIZED_COMMANDS = {
CAT_DASHBOARD: {
    "info": _("Dashboard completo per monitorare stato e statistiche del repository"), 
    "order": [
        CMD_REPO_STATUS_OVERVIEW,
        CMD_REPO_STATISTICS, 
        CMD_RECENT_ACTIVITY,
        CMD_BRANCH_STATUS,
        CMD_FILE_CHANGES_SUMMARY
    ], 
    "commands": {k: ORIGINAL_COMMANDS[k] for k in [
        CMD_REPO_STATUS_OVERVIEW,
        CMD_REPO_STATISTICS,
        CMD_RECENT_ACTIVITY, 
        CMD_BRANCH_STATUS,
        CMD_FILE_CHANGES_SUMMARY
    ]}
},
    CAT_REPO_OPS: {"info": _("Comandi fondamentali..."), "order": [ CMD_CLONE, CMD_INIT_REPO, CMD_ADD_TO_GITIGNORE, CMD_STATUS ], "commands": {k: ORIGINAL_COMMANDS[k] for k in [CMD_CLONE, CMD_INIT_REPO, CMD_ADD_TO_GITIGNORE, CMD_STATUS]}},
    CAT_LOCAL_CHANGES: {"info": _("Comandi per modifiche locali..."), "order": [ CMD_DIFF, CMD_DIFF_STAGED, CMD_ADD_ALL, CMD_COMMIT, CMD_AMEND_COMMIT, CMD_SHOW_COMMIT, CMD_LOG_CUSTOM ], "commands": {k: ORIGINAL_COMMANDS[k] for k in [CMD_DIFF, CMD_DIFF_STAGED, CMD_ADD_ALL, CMD_COMMIT, CMD_AMEND_COMMIT, CMD_SHOW_COMMIT, CMD_LOG_CUSTOM]}},
    CAT_BRANCH_TAG: {"info": _("Gestione branch e tag..."), "order": [ CMD_BRANCH_A, CMD_BRANCH_SHOW_CURRENT, CMD_BRANCH_NEW_NO_SWITCH, CMD_CHECKOUT_B, CMD_CHECKOUT_EXISTING, CMD_MERGE, CMD_BRANCH_D, CMD_BRANCH_FORCE_D, CMD_TAG_LIGHTWEIGHT ], "commands": {k: ORIGINAL_COMMANDS[k] for k in [CMD_BRANCH_A, CMD_BRANCH_SHOW_CURRENT, CMD_BRANCH_NEW_NO_SWITCH, CMD_CHECKOUT_B, CMD_CHECKOUT_EXISTING, CMD_MERGE, CMD_BRANCH_D, CMD_BRANCH_FORCE_D, CMD_TAG_LIGHTWEIGHT]}},
    CAT_REMOTE_OPS: {"info": _("Operazioni con remoti..."), "order": [ CMD_FETCH_ORIGIN, CMD_PULL, CMD_PUSH, CMD_REMOTE_ADD_ORIGIN, CMD_REMOTE_SET_URL, CMD_REMOTE_V, CMD_PUSH_DELETE_BRANCH ], "commands": {k: ORIGINAL_COMMANDS[k] for k in [CMD_FETCH_ORIGIN, CMD_PULL, CMD_PUSH, CMD_REMOTE_ADD_ORIGIN, CMD_REMOTE_SET_URL, CMD_REMOTE_V, CMD_PUSH_DELETE_BRANCH]}},
CAT_GITHUB_ACTIONS: {
        "info": _("Interagisci con GitHub Actions e Releases per il repository configurato."), # Info aggiornata
        "order": [
            CMD_GITHUB_CONFIGURE,
            CMD_GITHUB_CREATE_RELEASE,
            CMD_GITHUB_EDIT_RELEASE,
            CMD_GITHUB_DELETE_RELEASE, # Comand aggiunto qui
            CMD_GITHUB_SELECTED_RUN_LOGS,
            CMD_GITHUB_TRIGGER_WORKFLOW,      # ← AGGIUNGI QUI
            CMD_GITHUB_CANCEL_WORKFLOW,       # ← AGGIUNGI QUI  
            CMD_GITHUB_DOWNLOAD_SELECTED_ARTIFACT
        ],
        "commands": {k: ORIGINAL_COMMANDS[k] for k in [
            CMD_GITHUB_CONFIGURE,
            CMD_GITHUB_CREATE_RELEASE,
            CMD_GITHUB_DELETE_RELEASE, # Comando aggiunto qui
            CMD_GITHUB_SELECTED_RUN_LOGS,
            CMD_GITHUB_DOWNLOAD_SELECTED_ARTIFACT
        ]}
    },
    CAT_GITHUB_PR_ISSUES: {
        "info": _("Gestione completa di Pull Request e Issue: creazione, modifica, visualizzazione e chiusura."),
        "order": [
            CMD_GITHUB_CREATE_ISSUE,
            CMD_GITHUB_LIST_ISSUES,
            CMD_GITHUB_EDIT_ISSUE,
            CMD_GITHUB_DELETE_ISSUE,
            CMD_GITHUB_CREATE_PR,
            CMD_GITHUB_LIST_PRS,
            CMD_GITHUB_EDIT_PR,
            CMD_GITHUB_DELETE_PR
        ],
        "commands": {k: ORIGINAL_COMMANDS[k] for k in [
            CMD_GITHUB_CREATE_ISSUE,
            CMD_GITHUB_LIST_ISSUES,
            CMD_GITHUB_EDIT_ISSUE,
            CMD_GITHUB_DELETE_ISSUE,
            CMD_GITHUB_CREATE_PR,
            CMD_GITHUB_LIST_PRS,
            CMD_GITHUB_EDIT_PR,
            CMD_GITHUB_DELETE_PR
        ]}
    },
    CAT_STASH: {"info": _("Salvataggio temporaneo..."), "order": [CMD_STASH_SAVE, CMD_STASH_POP], "commands": {k: ORIGINAL_COMMANDS[k] for k in [CMD_STASH_SAVE, CMD_STASH_POP]}},
    CAT_SEARCH_UTIL: {"info": _("Ricerca e utilità..."), "order": [ CMD_GREP, CMD_LS_FILES ], "commands": {k: ORIGINAL_COMMANDS[k] for k in [CMD_GREP, CMD_LS_FILES]}},
    CAT_RESTORE_RESET: {"info": _("Ripristino e reset (cautela!)..."), "order": [ CMD_RESTORE_FILE, CMD_CHECKOUT_COMMIT_CLEAN, CMD_RESTORE_CLEAN, CMD_RESET_HARD_HEAD, CMD_MERGE_ABORT, CMD_CHECKOUT_DETACHED, CMD_RESET_TO_REMOTE, CMD_RESET_HARD_COMMIT ], "commands": {k: ORIGINAL_COMMANDS[k] for k in [CMD_RESTORE_FILE, CMD_CHECKOUT_COMMIT_CLEAN, CMD_RESTORE_CLEAN, CMD_RESET_HARD_HEAD, CMD_MERGE_ABORT, CMD_CHECKOUT_DETACHED, CMD_RESET_TO_REMOTE, CMD_RESET_HARD_COMMIT]}},
}
CATEGORY_DISPLAY_ORDER = [
    CAT_DASHBOARD,
    CAT_REPO_OPS, 
    CAT_LOCAL_CHANGES, 
    CAT_BRANCH_TAG,
    CAT_REMOTE_OPS, 
    CAT_GITHUB_ACTIONS, 
    CAT_GITHUB_PR_ISSUES, 
    CAT_STASH,
    CAT_SEARCH_UTIL, 
    CAT_RESTORE_RESET
]


class CreateIssueDialog(wx.Dialog):
    def __init__(self, parent, title, labels_list=None, assignees_list=None):
        super().__init__(parent, title=title, size=(600, 500))
        
        self.labels_list = labels_list or []
        self.assignees_list = assignees_list or []
        
        self.init_ui()
        self.Center()
    
    def init_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Titolo Issue
        title_label = wx.StaticText(panel, label=_("Titolo Issue*:"))
        main_sizer.Add(title_label, 0, wx.ALL, 5)
        
        self.title_ctrl = wx.TextCtrl(panel, size=(550, -1))
        main_sizer.Add(self.title_ctrl, 0, wx.EXPAND | wx.ALL, 5)
        
        # Descrizione
        desc_label = wx.StaticText(panel, label=_("Descrizione:"))
        main_sizer.Add(desc_label, 0, wx.ALL, 5)
        
        self.desc_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE, size=(550, 150))
        self.desc_ctrl.SetValue(_("## Descrizione\n\n## Passi per riprodurre\n1. \n2. \n3. \n\n## Comportamento atteso\n\n## Comportamento attuale\n\n## Informazioni aggiuntive\n"))
        main_sizer.Add(self.desc_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        
        # Sezione Labels e Assignees in due colonne
        labels_assignees_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Labels
        labels_box = wx.StaticBoxSizer(wx.VERTICAL, panel, _("Labels"))
        self.labels_checklist = wx.CheckListBox(panel, choices=self.labels_list, size=(250, 100))
        labels_box.Add(self.labels_checklist, 1, wx.EXPAND | wx.ALL, 5)
        labels_assignees_sizer.Add(labels_box, 1, wx.EXPAND | wx.ALL, 5)
        
        # Assignees
        assignees_box = wx.StaticBoxSizer(wx.VERTICAL, panel, _("Assignees"))
        self.assignees_checklist = wx.CheckListBox(panel, choices=self.assignees_list, size=(250, 100))
        assignees_box.Add(self.assignees_checklist, 1, wx.EXPAND | wx.ALL, 5)
        labels_assignees_sizer.Add(assignees_box, 1, wx.EXPAND | wx.ALL, 5)
        
        main_sizer.Add(labels_assignees_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # Priority e Type
        options_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Priority
        priority_label = wx.StaticText(panel, label=_("Priorità:"))
        self.priority_choice = wx.Choice(panel, choices=[_("Bassa"), _("Media"), _("Alta"), _("Critica")])
        self.priority_choice.SetSelection(1)  # Media come default
        
        options_sizer.Add(priority_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        options_sizer.Add(self.priority_choice, 0, wx.ALL, 5)
        
        # Type
        type_label = wx.StaticText(panel, label=_("Tipo:"))
        self.type_choice = wx.Choice(panel, choices=[_("Bug"), _("Feature"), _("Enhancement"), _("Documentation"), _("Question")])
        self.type_choice.SetSelection(0)  # Bug come default
        
        options_sizer.Add(type_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        options_sizer.Add(self.type_choice, 0, wx.ALL, 5)
        
        main_sizer.Add(options_sizer, 0, wx.ALL, 5)
        
        # Bottoni
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        btn_sizer.AddStretchSpacer()
        
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Annulla"))
        ok_btn = wx.Button(panel, wx.ID_OK, _("Crea Issue"))
        ok_btn.SetDefault()
        
        btn_sizer.Add(cancel_btn, 0, wx.ALL, 5)
        btn_sizer.Add(ok_btn, 0, wx.ALL, 5)
        
        main_sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        panel.SetSizer(main_sizer)
    
    def GetValues(self):
        # Labels selezionate
        selected_labels = []
        for i in range(self.labels_checklist.GetCount()):
            if self.labels_checklist.IsChecked(i):
                selected_labels.append(self.labels_list[i])
        
        # Assignees selezionati
        selected_assignees = []
        for i in range(self.assignees_checklist.GetCount()):
            if self.assignees_checklist.IsChecked(i):
                selected_assignees.append(self.assignees_list[i])
        
        # Aggiungi label automatiche basate su priorità e tipo
        priority_labels = {0: "priority:low", 1: "priority:medium", 2: "priority:high", 3: "priority:critical"}
        type_labels = {0: "bug", 1: "enhancement", 2: "enhancement", 3: "documentation", 4: "question"}
        
        if self.priority_choice.GetSelection() != -1:
            selected_labels.append(priority_labels[self.priority_choice.GetSelection()])
        
        if self.type_choice.GetSelection() != -1:
            selected_labels.append(type_labels[self.type_choice.GetSelection()])
        
        return {
            "title": self.title_ctrl.GetValue(),
            "body": self.desc_ctrl.GetValue(),
            "labels": list(set(selected_labels)),  # Rimuovi duplicati
            "assignees": selected_assignees
        }

class CreatePullRequestDialog(wx.Dialog):
    def __init__(self, parent, title, branches_list=None, current_branch=None):
        super().__init__(parent, title=title, size=(600, 550))
        
        self.branches_list = branches_list or []
        self.current_branch = current_branch
        
        self.init_ui()
        self.Center()
    
    def init_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Titolo PR
        title_label = wx.StaticText(panel, label=_("Titolo Pull Request*:"))
        main_sizer.Add(title_label, 0, wx.ALL, 5)
        
        self.title_ctrl = wx.TextCtrl(panel, size=(550, -1))
        main_sizer.Add(self.title_ctrl, 0, wx.EXPAND | wx.ALL, 5)
        
        # Branch selection
        branch_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Source branch (HEAD)
        source_label = wx.StaticText(panel, label=_("Da branch:"))
        self.source_choice = wx.Choice(panel, choices=self.branches_list)
        if self.current_branch and self.current_branch in self.branches_list:
            self.source_choice.SetSelection(self.branches_list.index(self.current_branch))
        
        # Target branch (BASE)
        target_label = wx.StaticText(panel, label=_("Verso branch:"))
        self.target_choice = wx.Choice(panel, choices=self.branches_list)
        # Default a main/master
        main_branches = ['main', 'master', 'develop']
        for main_branch in main_branches:
            if main_branch in self.branches_list:
                self.target_choice.SetSelection(self.branches_list.index(main_branch))
                break
        
        branch_sizer.Add(source_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        branch_sizer.Add(self.source_choice, 1, wx.ALL, 5)
        branch_sizer.Add(target_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        branch_sizer.Add(self.target_choice, 1, wx.ALL, 5)
        
        main_sizer.Add(branch_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # Descrizione
        desc_label = wx.StaticText(panel, label=_("Descrizione:"))
        main_sizer.Add(desc_label, 0, wx.ALL, 5)
        
        self.desc_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE, size=(550, 150))
        self.desc_ctrl.SetValue(_("## Modifiche\n\n## Tipo di cambiamento\n- [ ] Bug fix\n- [ ] Nuova feature\n- [ ] Breaking change\n- [ ] Documentazione\n\n## Testing\n- [ ] Ho testato le modifiche\n- [ ] Ho aggiunto/aggiornato i test\n\n## Checklist\n- [ ] Il codice segue le convenzioni del progetto\n- [ ] Ho fatto self-review del codice\n- [ ] Ho commentato il codice, specialmente nelle parti complesse\n"))
        main_sizer.Add(self.desc_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        
        # Opzioni
        options_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.draft_checkbox = wx.CheckBox(panel, label=_("Crea come Draft"))
        self.auto_merge_checkbox = wx.CheckBox(panel, label=_("Abilita auto-merge (se configurato)"))
        
        options_sizer.Add(self.draft_checkbox, 0, wx.ALL, 5)
        options_sizer.Add(self.auto_merge_checkbox, 0, wx.ALL, 5)
        
        main_sizer.Add(options_sizer, 0, wx.ALL, 5)
        
        # Bottoni
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        btn_sizer.AddStretchSpacer()
        
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Annulla"))
        ok_btn = wx.Button(panel, wx.ID_OK, _("Crea Pull Request"))
        ok_btn.SetDefault()
        
        btn_sizer.Add(cancel_btn, 0, wx.ALL, 5)
        btn_sizer.Add(ok_btn, 0, wx.ALL, 5)
        
        main_sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        panel.SetSizer(main_sizer)
    
    def GetValues(self):
        source_idx = self.source_choice.GetSelection()
        target_idx = self.target_choice.GetSelection()
        
        return {
            "title": self.title_ctrl.GetValue(),
            "body": self.desc_ctrl.GetValue(),
            "head": self.branches_list[source_idx] if source_idx != -1 else "",
            "base": self.branches_list[target_idx] if target_idx != -1 else "",
            "draft": self.draft_checkbox.GetValue(),
            "auto_merge": self.auto_merge_checkbox.GetValue()
        }

class EditReleaseDialog(wx.Dialog):
    def __init__(self, parent, title, release_data):
        super(EditReleaseDialog, self).__init__(parent, title=title, size=(650, 650))
        self.release_data = release_data
        self.panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Header con info release
        header_sizer = wx.BoxSizer(wx.HORIZONTAL)
        release_icon = wx.StaticText(self.panel, label="🏷️")
        release_icon_font = release_icon.GetFont()
        release_icon_font.SetPointSize(16)
        release_icon.SetFont(release_icon_font)
        
        header_text = wx.StaticText(self.panel, label=_("Modifica Release Esistente"))
        header_font = header_text.GetFont()
        header_font.SetWeight(wx.FONTWEIGHT_BOLD)
        header_font.SetPointSize(12)
        header_text.SetFont(header_font)
        
        header_sizer.Add(release_icon, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        header_sizer.Add(header_text, 1, wx.ALIGN_CENTER_VERTICAL)
        main_sizer.Add(header_sizer, 0, wx.ALL | wx.EXPAND, 10)

        # Separator line
        line = wx.StaticLine(self.panel)
        main_sizer.Add(line, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # Input Section
        input_box = wx.StaticBox(self.panel, label=_("Dettagli Release"))
        input_sizer = wx.StaticBoxSizer(input_box, wx.VERTICAL)
        
        input_grid_sizer = wx.FlexGridSizer(cols=2, gap=(10, 10))
        input_grid_sizer.AddGrowableCol(1, 1)

        # 1) Tag della release (non modificabile)
        tag_label = wx.StaticText(self.panel, label=_("Tag della Release:"))
        tag_font = tag_label.GetFont()
        tag_font.SetWeight(wx.FONTWEIGHT_BOLD)
        tag_label.SetFont(tag_font)
        
        tag_value = release_data.get('tag_name', 'N/A')
        self.tag_display = wx.StaticText(self.panel, label=tag_value)
        self.tag_display.SetForegroundColour(wx.Colour(0, 100, 0))  # Verde scuro
        tag_display_font = self.tag_display.GetFont()
        tag_display_font.SetWeight(wx.FONTWEIGHT_BOLD)
        self.tag_display.SetFont(tag_display_font)
        
        input_grid_sizer.Add(tag_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        input_grid_sizer.Add(self.tag_display, 1, wx.EXPAND | wx.ALL, 5)

        # 2) Titolo della release
        title_label = wx.StaticText(self.panel, label=_("Titolo della Release:*"))
        self.title_ctrl = wx.TextCtrl(self.panel, value=release_data.get('name', ''))
        input_grid_sizer.Add(title_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        input_grid_sizer.Add(self.title_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        input_sizer.Add(input_grid_sizer, 0, wx.EXPAND | wx.ALL, 10)

        # 3) Descrizione della release
        desc_label = wx.StaticText(self.panel, label=_("Descrizione della Release:"))
        input_sizer.Add(desc_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        
        self.desc_ctrl = wx.TextCtrl(self.panel, 
                                     style=wx.TE_MULTILINE, 
                                     size=(-1, 120), 
                                     value=release_data.get('body', ''))
        input_sizer.Add(self.desc_ctrl, 0, wx.EXPAND | wx.ALL, 10)

        main_sizer.Add(input_sizer, 0, wx.EXPAND | wx.ALL, 10)

        # 4) Asset esistenti (solo visualizzazione)
        existing_assets_box = wx.StaticBox(self.panel, label=_("Asset Attualmente Presenti"))
        existing_assets_sizer = wx.StaticBoxSizer(existing_assets_box, wx.VERTICAL)
        
        self.existing_assets_list_ctrl = wx.ListBox(self.panel, style=wx.LB_SINGLE, size=(-1, 100))
        
        # Conserva i dati originali degli asset per la gestione
        self.existing_assets_data = release_data.get('assets', [])
        self.assets_to_delete = []  # Lista degli asset da eliminare
        
        if self.existing_assets_data:
            for i, asset in enumerate(self.existing_assets_data):
                asset_name = asset.get('name', 'N/A')
                asset_size = asset.get('size', 0)
                size_kb = asset_size // 1024 if asset_size > 1024 else asset_size
                size_unit = "KB" if asset_size > 1024 else "B"
                download_count = asset.get('download_count', 0)
                
                asset_info = f"📎 {asset_name} ({size_kb} {size_unit}, {download_count} download)"
                self.existing_assets_list_ctrl.Append(asset_info)
        else:
            self.existing_assets_list_ctrl.Append(_("📭 Nessun asset presente in questa release"))
            self.existing_assets_list_ctrl.Enable(False)  # Disabilita se vuoto
        
        existing_assets_sizer.Add(self.existing_assets_list_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        
        # Bottoni per gestire asset esistenti
        if self.existing_assets_data:
            existing_buttons_sizer = wx.BoxSizer(wx.HORIZONTAL)
            self.delete_existing_button = wx.Button(self.panel, label=_("🗑️ Elimina Selezionati"))
            self.restore_deleted_button = wx.Button(self.panel, label=_("↶ Ripristina Eliminati"))
            
            existing_buttons_sizer.Add(self.delete_existing_button, 0, wx.ALL, 5)
            existing_buttons_sizer.Add(self.restore_deleted_button, 0, wx.ALL, 5)
            existing_buttons_sizer.AddStretchSpacer()
            
            existing_assets_sizer.Add(existing_buttons_sizer, 0, wx.EXPAND | wx.BOTTOM, 5)
        
        main_sizer.Add(existing_assets_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        # 5) Nuovi Asset da aggiungere
        new_assets_box = wx.StaticBox(self.panel, label=_("Nuovi Asset da Aggiungere"))
        new_assets_sizer = wx.StaticBoxSizer(new_assets_box, wx.VERTICAL)

        self.new_assets_list_ctrl = wx.ListBox(self.panel, style=wx.LB_SINGLE, size=(-1, 100))
        new_assets_sizer.Add(self.new_assets_list_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        # Bottoni per gestire i nuovi asset
        asset_buttons_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.add_asset_button = wx.Button(self.panel, label=_("➕ Aggiungi File..."))
        self.remove_asset_button = wx.Button(self.panel, label=_("➖ Rimuovi Selezionato"))
        self.clear_assets_button = wx.Button(self.panel, label=_("🗑️ Rimuovi Tutti"))

        asset_buttons_sizer.Add(self.add_asset_button, 0, wx.ALL, 5)
        asset_buttons_sizer.Add(self.remove_asset_button, 0, wx.ALL, 5)
        asset_buttons_sizer.AddStretchSpacer()
        asset_buttons_sizer.Add(self.clear_assets_button, 0, wx.ALL, 5)
        
        new_assets_sizer.Add(asset_buttons_sizer, 0, wx.EXPAND | wx.BOTTOM, 5)

        main_sizer.Add(new_assets_sizer, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Note informative
        info_text = wx.StaticText(self.panel, 
                                  label=_("ℹ️ Nota: Gli asset esistenti non verranno modificati, "
                                         "verranno solo aggiunti i nuovi file selezionati."))
        info_text.SetForegroundColour(wx.Colour(0, 0, 128))  # Blu scuro
        info_font = info_text.GetFont()
        info_font.SetPointSize(8)
        info_font.SetStyle(wx.FONTSTYLE_ITALIC)
        info_text.SetFont(info_font)
        main_sizer.Add(info_text, 0, wx.ALL | wx.EXPAND, 10)

        # Separator line
        line2 = wx.StaticLine(self.panel)
        main_sizer.Add(line2, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        # Pulsanti OK / Cancel
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.cancel_button = wx.Button(self.panel, wx.ID_CANCEL, label=_("❌ Annulla"))
        self.ok_button = wx.Button(self.panel, wx.ID_OK, label=_("✅ Aggiorna Release"))
        self.ok_button.SetDefault()
        
        button_sizer.AddStretchSpacer()
        button_sizer.Add(self.cancel_button, 0, wx.ALL, 10)
        button_sizer.Add(self.ok_button, 0, wx.ALL, 10)
        
        main_sizer.Add(button_sizer, 0, wx.EXPAND | wx.ALL, 5)

        self.panel.SetSizer(main_sizer)
        self.title_ctrl.SetFocus()

        # Bind events
        self.add_asset_button.Bind(wx.EVT_BUTTON, self.OnAddAssets)
        self.remove_asset_button.Bind(wx.EVT_BUTTON, self.OnRemoveAsset)
        self.clear_assets_button.Bind(wx.EVT_BUTTON, self.OnClearAssets)
        self.ok_button.Bind(wx.EVT_BUTTON, self.OnOk)
        
        # Bind eventi per asset esistenti (se ci sono)
        if self.existing_assets_data:
            self.delete_existing_button.Bind(wx.EVT_BUTTON, self.OnDeleteExistingAssets)
            self.restore_deleted_button.Bind(wx.EVT_BUTTON, self.OnRestoreDeletedAssets)
            
        # Lista per memorizzare i percorsi dei nuovi file
        self.new_assets_paths = []

        # Centro il dialogo
        self.Center()

    def OnAddAssets(self, event):
        """Gestisce l'aggiunta di nuovi file asset."""
        file_dlg = wx.FileDialog(
            self,
            _("Seleziona file da aggiungere come nuovi asset (Ctrl/Cmd per selezione multipla)"),
            wildcard=_("Tutti i file (*.*)|*.*"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE
        )
        
        if file_dlg.ShowModal() == wx.ID_OK:
            paths = file_dlg.GetPaths()
            added_count = 0
            
            for path in paths:
                if path not in self.new_assets_paths:
                    self.new_assets_paths.append(path)
                    filename = os.path.basename(path)
                    # Calcola dimensione file
                    try:
                        file_size = os.path.getsize(path)
                        size_kb = file_size // 1024
                        display_name = f"{filename} ({size_kb} KB)"
                    except OSError:
                        display_name = f"{filename} (dimensione sconosciuta)"
                    
                    self.new_assets_list_ctrl.Append(display_name)
                    added_count += 1
            
            if added_count > 0:
                self.UpdateButtonStates()
                
        file_dlg.Destroy()

    def OnRemoveAsset(self, event):
        """Rimuove l'asset selezionato dalla lista."""
        selected_index = self.new_assets_list_ctrl.GetSelection()
        if selected_index == wx.NOT_FOUND:
            wx.MessageBox(_("Seleziona un file da rimuovere."), 
                         _("Nessuna Selezione"), wx.OK | wx.ICON_INFORMATION, self)
            return
        
        del self.new_assets_paths[selected_index]
        self.new_assets_list_ctrl.Delete(selected_index)
        self.UpdateButtonStates()
    
    def OnClearAssets(self, event):
        """Rimuove tutti i nuovi asset dalla lista."""
        if not self.new_assets_paths:
            return
            
        confirm_dlg = wx.MessageDialog(
            self,
            _("Sei sicuro di voler rimuovere tutti i nuovi asset dalla lista?"),
            _("Conferma Rimozione"),
            wx.YES_NO | wx.ICON_QUESTION
        )
        
        if confirm_dlg.ShowModal() == wx.ID_YES:
            self.new_assets_paths.clear()
            self.new_assets_list_ctrl.Clear()
            self.UpdateButtonStates()
        
        confirm_dlg.Destroy()

    def UpdateButtonStates(self):
        """Aggiorna lo stato dei bottoni in base al contenuto della lista."""
        has_items = len(self.new_assets_paths) > 0
        self.remove_asset_button.Enable(has_items)
        self.clear_assets_button.Enable(has_items)

    def OnOk(self, event):
        """Valida i dati e chiude il dialogo."""
        release_name = self.title_ctrl.GetValue().strip()
        
        if not release_name:
            wx.MessageBox(_("Il Titolo della Release è obbligatorio."), 
                         _("Input Mancante"), wx.OK | wx.ICON_ERROR, self)
            self.title_ctrl.SetFocus()
            return
        
        # Verifica che i file esistano ancora
        missing_files = []
        for file_path in self.new_assets_paths:
            if not os.path.exists(file_path):
                missing_files.append(os.path.basename(file_path))
        
        if missing_files:
            missing_list = "\n".join(missing_files)
            wx.MessageBox(
                _("I seguenti file non sono più accessibili:\n\n{}\n\n"
                  "Rimuovili dalla lista o verifica che esistano ancora.").format(missing_list),
                _("File Non Trovati"), wx.OK | wx.ICON_ERROR, self
            )
            return
        
        self.EndModal(wx.ID_OK)
        
    def OnDeleteExistingAssets(self, event):
        """Segna l'asset esistente selezionato per l'eliminazione."""
        selected_index = self.existing_assets_list_ctrl.GetSelection()
        if selected_index == wx.NOT_FOUND:
            wx.MessageBox(_("Seleziona un asset da eliminare."), 
                         _("Nessuna Selezione"), wx.OK | wx.ICON_INFORMATION, self)
            return
        
        # Verifica se l'asset non è già segnato per eliminazione
        if selected_index < len(self.existing_assets_data):
            asset = self.existing_assets_data[selected_index]
            if asset in self.assets_to_delete:
                wx.MessageBox(_("L'asset selezionato è già segnato per l'eliminazione."), 
                             _("Già Segnato"), wx.OK | wx.ICON_INFORMATION, self)
                return
            
            # Conferma eliminazione
            asset_name = asset['name']
            confirm_msg = _("Sei sicuro di voler eliminare questo asset dalla release?\n\n"
                           "• {}\n\n"
                           "ATTENZIONE: Questa operazione è irreversibile!").format(asset_name)
            
            confirm_dlg = wx.MessageDialog(
                self, confirm_msg, _("Conferma Eliminazione Asset"), 
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING
            )
            
            if confirm_dlg.ShowModal() == wx.ID_YES:
                # Aggiungi alla lista di eliminazione e aggiorna visualizzazione
                self.assets_to_delete.append(asset)
                # Cambia il colore dell'item per indicare che sarà eliminato
                current_text = self.existing_assets_list_ctrl.GetString(selected_index)
                new_text = f"🗑️ [DA ELIMINARE] {current_text[2:]}"  # Rimuove l'emoji originale
                self.existing_assets_list_ctrl.SetString(selected_index, new_text)
                
                self.UpdateExistingButtonStates()
            
            confirm_dlg.Destroy()
    def OnRestoreDeletedAssets(self, event):
        """Ripristina gli asset segnati per l'eliminazione."""
        if not self.assets_to_delete:
            wx.MessageBox(_("Nessun asset da ripristinare."), 
                         _("Nessun Asset"), wx.OK | wx.ICON_INFORMATION, self)
            return
        
        # Ripristina tutti gli asset segnati per eliminazione
        self.assets_to_delete.clear()
        
        # Ripristina la visualizzazione originale
        for i, asset in enumerate(self.existing_assets_data):
            asset_name = asset.get('name', 'N/A')
            asset_size = asset.get('size', 0)
            size_kb = asset_size // 1024 if asset_size > 1024 else asset_size
            size_unit = "KB" if asset_size > 1024 else "B"
            download_count = asset.get('download_count', 0)
            
            asset_info = f"📎 {asset_name} ({size_kb} {size_unit}, {download_count} download)"
            self.existing_assets_list_ctrl.SetString(i, asset_info)
        
        self.UpdateExistingButtonStates()
        wx.MessageBox(_("Tutti gli asset sono stati ripristinati."), 
                     _("Ripristino Completato"), wx.OK | wx.ICON_INFORMATION, self)

    def UpdateExistingButtonStates(self):
        """Aggiorna lo stato dei bottoni per gli asset esistenti."""
        if hasattr(self, 'delete_existing_button'):
            has_assets = len(self.existing_assets_data) > 0
            has_deleted = len(self.assets_to_delete) > 0
            
            self.delete_existing_button.Enable(has_assets)
            self.restore_deleted_button.Enable(has_deleted)
            
    def GetValues(self):
        """Restituisce i valori inseriti dall'utente."""
        return {
            "tag_name": self.release_data.get('tag_name', ''),  # Non modificabile
            "release_name": self.title_ctrl.GetValue().strip(),
            "release_body": self.desc_ctrl.GetValue().strip(),
            "new_files_to_upload": self.new_assets_paths.copy(),
            "assets_to_delete": self.assets_to_delete.copy(),
            "release_id": self.release_data.get('id'),
            "original_release_data": self.release_data
        }
        
    def GetReleaseInfo(self):
        """Restituisce informazioni sulla release per debug/log."""
        return {
            "tag": self.release_data.get('tag_name', 'N/A'),
            "current_title": self.release_data.get('name', 'N/A'),
            "new_title": self.title_ctrl.GetValue().strip(),
            "assets_count": len(self.release_data.get('assets', [])),
            "new_assets_count": len(self.new_assets_paths)
        }

class IssueManagementDialog(wx.Dialog):
    def __init__(self, parent, issue_data, github_owner, github_repo, github_token):
        super().__init__(parent, title=f"Gestione Issue #{issue_data['number']}: {issue_data['title'][:50]}...", size=(850, 750))
        
        self.issue_data = issue_data
        self.github_owner = github_owner
        self.github_repo = github_repo
        self.github_token = github_token
        self.comments_data = []
        
        self.create_ui()
        self.load_comments()
        self.Center()
    
    def create_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Header con info issue
        header_box = wx.StaticBox(panel, label=_("📋 Dettagli Issue"))
        header_sizer = wx.StaticBoxSizer(header_box, wx.VERTICAL)
        
        # Titolo e stato
        title_sizer = wx.BoxSizer(wx.HORIZONTAL)
        title_text = f"#{self.issue_data['number']}: {self.issue_data['title']}"
        title_label = wx.StaticText(panel, label=title_text)
        title_font = title_label.GetFont()
        title_font.SetWeight(wx.FONTWEIGHT_BOLD)
        title_font.SetPointSize(12)
        title_label.SetFont(title_font)
        
        state_icon = "🟢" if self.issue_data['state'] == 'open' else "🔴"
        state_label = wx.StaticText(panel, label=f"{state_icon} {self.issue_data['state'].upper()}")
        state_font = state_label.GetFont()
        state_font.SetWeight(wx.FONTWEIGHT_BOLD)
        state_label.SetFont(state_font)
        
        title_sizer.Add(title_label, 1, wx.EXPAND | wx.ALL, 5)
        title_sizer.Add(state_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        header_sizer.Add(title_sizer, 0, wx.EXPAND)
        
        # Info aggiuntive in formato tabella
        info_grid = wx.FlexGridSizer(cols=2, gap=(10, 5))
        info_grid.AddGrowableCol(1, 1)
        
        # Autore
        author_label = wx.StaticText(panel, label="👤 Autore:")
        author_value = wx.StaticText(panel, label=self.issue_data['user']['login'])
        info_grid.Add(author_label, 0, wx.ALIGN_CENTER_VERTICAL)
        info_grid.Add(author_value, 1, wx.EXPAND)
        
        # Date
        created_label = wx.StaticText(panel, label="📅 Creata:")
        created_value = wx.StaticText(panel, label=self.issue_data['created_at'][:10])
        info_grid.Add(created_label, 0, wx.ALIGN_CENTER_VERTICAL)
        info_grid.Add(created_value, 1, wx.EXPAND)
        
        updated_label = wx.StaticText(panel, label="🔄 Aggiornata:")
        updated_value = wx.StaticText(panel, label=self.issue_data['updated_at'][:10])
        info_grid.Add(updated_label, 0, wx.ALIGN_CENTER_VERTICAL)
        info_grid.Add(updated_value, 1, wx.EXPAND)
        
        # Assignees
        if self.issue_data.get('assignees'):
            assignees_label = wx.StaticText(panel, label="👥 Assegnata a:")
            assignees_text = ", ".join([a['login'] for a in self.issue_data['assignees']])
            assignees_value = wx.StaticText(panel, label=assignees_text)
            info_grid.Add(assignees_label, 0, wx.ALIGN_CENTER_VERTICAL)
            info_grid.Add(assignees_value, 1, wx.EXPAND)
        
        # Labels
        if self.issue_data.get('labels'):
            labels_label = wx.StaticText(panel, label="🏷️ Labels:")
            labels_text = ", ".join([l['name'] for l in self.issue_data['labels']])
            labels_value = wx.StaticText(panel, label=labels_text)
            info_grid.Add(labels_label, 0, wx.ALIGN_CENTER_VERTICAL)
            info_grid.Add(labels_value, 1, wx.EXPAND)
        
        header_sizer.Add(info_grid, 0, wx.EXPAND | wx.ALL, 5)
        
        # Descrizione
        if self.issue_data.get('body') and self.issue_data['body'].strip():
            desc_label = wx.StaticText(panel, label=_("📝 Descrizione:"))
            desc_font = desc_label.GetFont()
            desc_font.SetWeight(wx.FONTWEIGHT_BOLD)
            desc_label.SetFont(desc_font)
            header_sizer.Add(desc_label, 0, wx.TOP | wx.LEFT | wx.RIGHT, 10)
            
            desc_text = wx.TextCtrl(panel, value=self.issue_data['body'], 
                                   style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 120))
            desc_text.SetBackgroundColour(wx.Colour(250, 250, 250))
            header_sizer.Add(desc_text, 0, wx.EXPAND | wx.ALL, 5)
        
        main_sizer.Add(header_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Separator
        line1 = wx.StaticLine(panel)
        main_sizer.Add(line1, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        
        # Sezione commenti
        comments_box = wx.StaticBox(panel, label=_("💬 Commenti"))
        comments_sizer = wx.StaticBoxSizer(comments_box, wx.VERTICAL)
        
        # Info commenti e refresh
        comments_info_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.comments_count_label = wx.StaticText(panel, label=_("Caricamento commenti..."))
        self.refresh_btn = wx.Button(panel, label=_("🔄 Aggiorna"))
        self.refresh_btn.Bind(wx.EVT_BUTTON, self.OnRefreshComments)
        
        comments_info_sizer.Add(self.comments_count_label, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        comments_info_sizer.Add(self.refresh_btn, 0, wx.ALL, 5)
        comments_sizer.Add(comments_info_sizer, 0, wx.EXPAND)
        
        # Lista commenti con scrollbar
        self.comments_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL, size=(-1, 250))
        # Font monospazio per migliore leggibilità
        mono_font = wx.Font(9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        if mono_font.IsOk():
            self.comments_ctrl.SetFont(mono_font)
        
        comments_sizer.Add(self.comments_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        
        main_sizer.Add(comments_sizer, 1, wx.EXPAND | wx.ALL, 10)
        
        # Separator
        line2 = wx.StaticLine(panel)
        main_sizer.Add(line2, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        
        # Nuovo commento
        new_comment_box = wx.StaticBox(panel, label=_("✍️ Scrivi Nuovo Commento"))
        new_comment_sizer = wx.StaticBoxSizer(new_comment_box, wx.VERTICAL)
        
        self.new_comment_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE, size=(-1, 100))
        self.new_comment_ctrl.SetHint(_("Scrivi il tuo commento qui... Supporta Markdown!"))
        new_comment_sizer.Add(self.new_comment_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        
        # Contatore caratteri e bottoni
        comment_bottom_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.char_count_label = wx.StaticText(panel, label="0 caratteri")
        self.char_count_label.SetForegroundColour(wx.Colour(128, 128, 128))
        
        self.send_comment_btn = wx.Button(panel, label=_("📤 Invia Commento"))
        self.send_comment_btn.Bind(wx.EVT_BUTTON, self.OnSendComment)
        
        self.clear_comment_btn = wx.Button(panel, label=_("🗑️ Pulisci"))
        self.clear_comment_btn.Bind(wx.EVT_BUTTON, self.OnClearComment)
        
        comment_bottom_sizer.Add(self.char_count_label, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        comment_bottom_sizer.Add(self.clear_comment_btn, 0, wx.ALL, 5)
        comment_bottom_sizer.Add(self.send_comment_btn, 0, wx.ALL, 5)
        
        new_comment_sizer.Add(comment_bottom_sizer, 0, wx.EXPAND)
        main_sizer.Add(new_comment_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Bind per contatore caratteri
        self.new_comment_ctrl.Bind(wx.EVT_TEXT, self.OnCommentTextChanged)
        
        # Separator finale
        line3 = wx.StaticLine(panel)
        main_sizer.Add(line3, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        
        # Bottoni finali
        final_buttons_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Info URL
        url_label = wx.StaticText(panel, label=f"🔗 {self.issue_data['html_url']}")
        url_label.SetForegroundColour(wx.Colour(0, 0, 255))
        
        # Pulsanti
        self.open_browser_btn = wx.Button(panel, label=_("🌐 Apri nel Browser"))
        self.open_browser_btn.Bind(wx.EVT_BUTTON, self.OnOpenInBrowser)
        
        close_btn = wx.Button(panel, wx.ID_CLOSE, label=_("✖️ Chiudi"))
        close_btn.Bind(wx.EVT_BUTTON, self.OnClose)
        close_btn.SetDefault()
        close_btn.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_CLOSE))
        final_buttons_sizer.Add(url_label, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        final_buttons_sizer.Add(self.open_browser_btn, 0, wx.ALL, 5)
        final_buttons_sizer.Add(close_btn, 0, wx.ALL, 5)
        
        main_sizer.Add(final_buttons_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        panel.SetSizer(main_sizer)
    
    def load_comments(self):
        """Carica i commenti della issue."""
        if not self.github_token:
            self.comments_ctrl.SetValue(_("❌ Token GitHub necessario per visualizzare i commenti."))
            self.send_comment_btn.Enable(False)
            self.comments_count_label.SetLabel(_("Token mancante"))
            return
        
        self.comments_count_label.SetLabel(_("Caricamento..."))
        wx.SafeYield()
        
        headers = {"Authorization": f"Bearer {self.github_token}", "Accept": "application/vnd.github.v3+json"}
        comments_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/issues/{self.issue_data['number']}/comments"
        
        try:
            response = requests.get(comments_url, headers=headers, timeout=15)
            response.raise_for_status()
            self.comments_data = response.json()
            
            comment_count = len(self.comments_data)
            self.comments_count_label.SetLabel(f"📊 {comment_count} commenti totali")
            
            if not self.comments_data:
                self.comments_ctrl.SetValue(_("📭 Nessun commento ancora presente.\n\n💡 Scrivi il primo commento usando il campo qui sotto!"))
            else:
                comments_text = ""
                for i, comment in enumerate(self.comments_data):
                    author = comment['user']['login']
                    created_at = comment['created_at'][:16].replace('T', ' ')
                    updated_at = comment.get('updated_at', '')
                    body = comment['body']
                    
                    # Header del commento
                    comments_text += f"{'='*80}\n"
                    comments_text += f"💬 Commento #{i+1} - {author} - {created_at}"
                    
                    if updated_at and updated_at != comment['created_at']:
                        comments_text += f" (modificato: {updated_at[:16].replace('T', ' ')})"
                    
                    comments_text += f"\n{'='*80}\n"
                    comments_text += f"{body}\n\n"
                
                self.comments_ctrl.SetValue(comments_text)
                # Scroll all'inizio
                self.comments_ctrl.SetInsertionPoint(0)
        
        except requests.exceptions.RequestException as e:
            error_msg = f"❌ Errore nel caricare i commenti: {e}"
            self.comments_ctrl.SetValue(error_msg)
            self.send_comment_btn.Enable(False)
            self.comments_count_label.SetLabel(_("Errore caricamento"))
    
    def OnRefreshComments(self, event):
        """Ricarica i commenti."""
        self.load_comments()
    
    def OnCommentTextChanged(self, event):
        """Aggiorna il contatore caratteri."""
        text = self.new_comment_ctrl.GetValue()
        char_count = len(text)
        self.char_count_label.SetLabel(f"{char_count} caratteri")
        
        # Cambia colore se troppo lungo
        if char_count > 65536:  # Limite GitHub
            self.char_count_label.SetForegroundColour(wx.Colour(255, 0, 0))
        else:
            self.char_count_label.SetForegroundColour(wx.Colour(128, 128, 128))
        
        event.Skip()
    
    def OnClearComment(self, event):
        """Pulisce il campo commento."""
        if self.new_comment_ctrl.GetValue().strip():
            dlg = wx.MessageDialog(self, _("Sei sicuro di voler cancellare il commento che stai scrivendo?"), 
                                 _("Conferma Cancellazione"), wx.YES_NO | wx.ICON_QUESTION)
            if dlg.ShowModal() == wx.ID_YES:
                self.new_comment_ctrl.SetValue("")
            dlg.Destroy()
    
    def OnSendComment(self, event):
        """Invia un nuovo commento."""
        comment_text = self.new_comment_ctrl.GetValue().strip()
        if not comment_text:
            wx.MessageBox(_("Inserisci un commento prima di inviare."), _("Commento Vuoto"), 
                         wx.OK | wx.ICON_WARNING, self)
            self.new_comment_ctrl.SetFocus()
            return
        
        if len(comment_text) > 65536:
            wx.MessageBox(_("Il commento è troppo lungo (massimo 65536 caratteri)."), 
                         _("Commento Troppo Lungo"), wx.OK | wx.ICON_ERROR, self)
            return
        
        if not self.github_token:
            wx.MessageBox(_("Token GitHub necessario per inviare commenti."), 
                         _("Token Mancante"), wx.OK | wx.ICON_ERROR, self)
            return
        
        # Conferma invio
        confirm_dlg = wx.MessageDialog(self, 
                                     _("Sei sicuro di voler inviare questo commento?\n\nIl commento sarà pubblico e visibile a tutti."), 
                                     _("Conferma Invio Commento"), wx.YES_NO | wx.ICON_QUESTION)
        
        if confirm_dlg.ShowModal() != wx.ID_YES:
            confirm_dlg.Destroy()
            return
        confirm_dlg.Destroy()
        
        # Disabilita pulsante durante invio
        self.send_comment_btn.Enable(False)
        self.send_comment_btn.SetLabel(_("📤 Invio..."))
        wx.SafeYield()
        
        headers = {"Authorization": f"Bearer {self.github_token}", "Accept": "application/vnd.github.v3+json"}
        comments_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/issues/{self.issue_data['number']}/comments"
        
        payload = {"body": comment_text}
        
        try:
            response = requests.post(comments_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            
            wx.MessageBox(_("✅ Commento inviato con successo!"), _("Commento Inviato"), 
                         wx.OK | wx.ICON_INFORMATION, self)
            self.new_comment_ctrl.SetValue("")  # Pulisce il campo
            self.load_comments()  # Ricarica i commenti
            
        except requests.exceptions.RequestException as e:
            wx.MessageBox(f"❌ Errore nell'inviare il commento: {e}", _("Errore Invio"), 
                         wx.OK | wx.ICON_ERROR, self)
        finally:
            # Riabilita pulsante
            self.send_comment_btn.Enable(True)
            self.send_comment_btn.SetLabel(_("📤 Invia Commento"))
    
    def OnOpenInBrowser(self, event):
        """Apre la issue nel browser."""
        try:
            webbrowser.open(self.issue_data['html_url'])
        except Exception as e:
            wx.MessageBox(f"Errore nell'aprire il browser: {e}", "Errore", wx.OK | wx.ICON_ERROR, self)
    
    def OnClose(self, event):
        """Chiude il dialog."""
        # Controlla se c'è testo non salvato
        if self.new_comment_ctrl.GetValue().strip():
            dlg = wx.MessageDialog(self, 
                                 _("Hai un commento non inviato. Sei sicuro di voler chiudere?"), 
                                 _("Commento Non Salvato"), wx.YES_NO | wx.ICON_QUESTION)
            if dlg.ShowModal() != wx.ID_YES:
                dlg.Destroy()
                return
            dlg.Destroy()
        
        self.EndModal(wx.ID_CLOSE)

class PullRequestManagementDialog(wx.Dialog):
    def __init__(self, parent, pr_data, github_owner, github_repo, github_token):
        super().__init__(parent, title=f"Gestione PR #{pr_data['number']}: {pr_data['title'][:50]}...", size=(850, 750))
        
        self.pr_data = pr_data
        self.github_owner = github_owner
        self.github_repo = github_repo
        self.github_token = github_token
        self.comments_data = []
        
        self.create_ui()
        self.load_comments()
        self.Center()
    
    def create_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Header con info PR
        header_box = wx.StaticBox(panel, label=_("🔀 Dettagli Pull Request"))
        header_sizer = wx.StaticBoxSizer(header_box, wx.VERTICAL)
        
        # Titolo e stato
        title_sizer = wx.BoxSizer(wx.HORIZONTAL)
        title_text = f"#{self.pr_data['number']}: {self.pr_data['title']}"
        title_label = wx.StaticText(panel, label=title_text)
        title_font = title_label.GetFont()
        title_font.SetWeight(wx.FONTWEIGHT_BOLD)
        title_font.SetPointSize(12)
        title_label.SetFont(title_font)
        
        # Stato PR più dettagliato
        if self.pr_data.get('merged_at'):
            state_icon = "🟣"
            state_text = "MERGED"
        elif self.pr_data['state'] == 'open':
            state_icon = "🟢"
            state_text = "OPEN"
        else:
            state_icon = "🔴"
            state_text = "CLOSED"
        
        if self.pr_data.get('draft', False):
            state_text += " (DRAFT)"
        
        state_label = wx.StaticText(panel, label=f"{state_icon} {state_text}")
        state_font = state_label.GetFont()
        state_font.SetWeight(wx.FONTWEIGHT_BOLD)
        state_label.SetFont(state_font)
        
        title_sizer.Add(title_label, 1, wx.EXPAND | wx.ALL, 5)
        title_sizer.Add(state_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        header_sizer.Add(title_sizer, 0, wx.EXPAND)
        
        # Info aggiuntive in formato tabella
        info_grid = wx.FlexGridSizer(cols=2, gap=(10, 5))
        info_grid.AddGrowableCol(1, 1)
        
        # Autore
        author_label = wx.StaticText(panel, label="👤 Autore:")
        author_value = wx.StaticText(panel, label=self.pr_data['user']['login'])
        info_grid.Add(author_label, 0, wx.ALIGN_CENTER_VERTICAL)
        info_grid.Add(author_value, 1, wx.EXPAND)
        
        # Branch info
        branch_label = wx.StaticText(panel, label="🌿 Branch:")
        branch_text = f"{self.pr_data['head']['ref']} → {self.pr_data['base']['ref']}"
        branch_value = wx.StaticText(panel, label=branch_text)
        info_grid.Add(branch_label, 0, wx.ALIGN_CENTER_VERTICAL)
        info_grid.Add(branch_value, 1, wx.EXPAND)
        
        # Date
        created_label = wx.StaticText(panel, label="📅 Creata:")
        created_value = wx.StaticText(panel, label=self.pr_data['created_at'][:10])
        info_grid.Add(created_label, 0, wx.ALIGN_CENTER_VERTICAL)
        info_grid.Add(created_value, 1, wx.EXPAND)
        
        updated_label = wx.StaticText(panel, label="🔄 Aggiornata:")
        updated_value = wx.StaticText(panel, label=self.pr_data['updated_at'][:10])
        info_grid.Add(updated_label, 0, wx.ALIGN_CENTER_VERTICAL)
        info_grid.Add(updated_value, 1, wx.EXPAND)
        
        # Data merge se presente
        if self.pr_data.get('merged_at'):
            merged_label = wx.StaticText(panel, label="🎯 Merged:")
            merged_value = wx.StaticText(panel, label=self.pr_data['merged_at'][:10])
            info_grid.Add(merged_label, 0, wx.ALIGN_CENTER_VERTICAL)
            info_grid.Add(merged_value, 1, wx.EXPAND)
        
        # Stato merge
        mergeable_label = wx.StaticText(panel, label="🔀 Mergeable:")
        mergeable_state = self.pr_data.get('mergeable_state', 'unknown')
        mergeable_icons = {
            'clean': '✅ Clean',
            'dirty': '❌ Conflicts',
            'unknown': '❓ Unknown',
            'blocked': '🚫 Blocked',
            'behind': '⏭️ Behind',
            'unstable': '⚠️ Unstable'
        }
        mergeable_text = mergeable_icons.get(mergeable_state, f"❓ {mergeable_state}")
        mergeable_value = wx.StaticText(panel, label=mergeable_text)
        info_grid.Add(mergeable_label, 0, wx.ALIGN_CENTER_VERTICAL)
        info_grid.Add(mergeable_value, 1, wx.EXPAND)
        
        # Commit e file stats
        if 'commits' in self.pr_data or 'changed_files' in self.pr_data:
            stats_label = wx.StaticText(panel, label="📊 Stats:")
            stats_text = ""
            if 'commits' in self.pr_data:
                stats_text += f"{self.pr_data['commits']} commits"
            if 'changed_files' in self.pr_data:
                if stats_text:
                    stats_text += ", "
                stats_text += f"{self.pr_data['changed_files']} files"
            if 'additions' in self.pr_data and 'deletions' in self.pr_data:
                stats_text += f" (+{self.pr_data['additions']} -{self.pr_data['deletions']})"
            
            stats_value = wx.StaticText(panel, label=stats_text)
            info_grid.Add(stats_label, 0, wx.ALIGN_CENTER_VERTICAL)
            info_grid.Add(stats_value, 1, wx.EXPAND)
        
        # Reviewers se presenti
        if self.pr_data.get('requested_reviewers'):
            reviewers_label = wx.StaticText(panel, label="👥 Reviewers:")
            reviewers_text = ", ".join([r['login'] for r in self.pr_data['requested_reviewers']])
            reviewers_value = wx.StaticText(panel, label=reviewers_text)
            info_grid.Add(reviewers_label, 0, wx.ALIGN_CENTER_VERTICAL)
            info_grid.Add(reviewers_value, 1, wx.EXPAND)
        
        # Labels
        if self.pr_data.get('labels'):
            labels_label = wx.StaticText(panel, label="🏷️ Labels:")
            labels_text = ", ".join([l['name'] for l in self.pr_data['labels']])
            labels_value = wx.StaticText(panel, label=labels_text)
            info_grid.Add(labels_label, 0, wx.ALIGN_CENTER_VERTICAL)
            info_grid.Add(labels_value, 1, wx.EXPAND)
        
        header_sizer.Add(info_grid, 0, wx.EXPAND | wx.ALL, 5)
        
        # Descrizione
        if self.pr_data.get('body') and self.pr_data['body'].strip():
            desc_label = wx.StaticText(panel, label=_("📝 Descrizione:"))
            desc_font = desc_label.GetFont()
            desc_font.SetWeight(wx.FONTWEIGHT_BOLD)
            desc_label.SetFont(desc_font)
            header_sizer.Add(desc_label, 0, wx.TOP | wx.LEFT | wx.RIGHT, 10)
            
            desc_text = wx.TextCtrl(panel, value=self.pr_data['body'], 
                                   style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 120))
            desc_text.SetBackgroundColour(wx.Colour(250, 250, 250))
            header_sizer.Add(desc_text, 0, wx.EXPAND | wx.ALL, 5)
        
        main_sizer.Add(header_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Separator
        line1 = wx.StaticLine(panel)
        main_sizer.Add(line1, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        
        # Sezione commenti
        comments_box = wx.StaticBox(panel, label=_("💬 Commenti e Review"))
        comments_sizer = wx.StaticBoxSizer(comments_box, wx.VERTICAL)
        
        # Info commenti e refresh
        comments_info_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.comments_count_label = wx.StaticText(panel, label=_("Caricamento commenti..."))
        self.refresh_btn = wx.Button(panel, label=_("🔄 Aggiorna"))
        self.refresh_btn.Bind(wx.EVT_BUTTON, self.OnRefreshComments)
        
        comments_info_sizer.Add(self.comments_count_label, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        comments_info_sizer.Add(self.refresh_btn, 0, wx.ALL, 5)
        comments_sizer.Add(comments_info_sizer, 0, wx.EXPAND)
        
        # Lista commenti con scrollbar
        self.comments_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL, size=(-1, 250))
        # Font monospazio per migliore leggibilità
        mono_font = wx.Font(9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        if mono_font.IsOk():
            self.comments_ctrl.SetFont(mono_font)
        
        comments_sizer.Add(self.comments_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        
        main_sizer.Add(comments_sizer, 1, wx.EXPAND | wx.ALL, 10)
        
        # Separator
        line2 = wx.StaticLine(panel)
        main_sizer.Add(line2, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        
        # Nuovo commento
        new_comment_box = wx.StaticBox(panel, label=_("✍️ Scrivi Nuovo Commento"))
        new_comment_sizer = wx.StaticBoxSizer(new_comment_box, wx.VERTICAL)
        
        self.new_comment_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE, size=(-1, 100))
        self.new_comment_ctrl.SetHint(_("Scrivi il tuo commento sulla PR... Supporta Markdown!"))
        new_comment_sizer.Add(self.new_comment_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        
        # Contatore caratteri e bottoni
        comment_bottom_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.char_count_label = wx.StaticText(panel, label="0 caratteri")
        self.char_count_label.SetForegroundColour(wx.Colour(128, 128, 128))
        
        self.send_comment_btn = wx.Button(panel, label=_("📤 Invia Commento"))
        self.send_comment_btn.Bind(wx.EVT_BUTTON, self.OnSendComment)
        
        self.clear_comment_btn = wx.Button(panel, label=_("🗑️ Pulisci"))
        self.clear_comment_btn.Bind(wx.EVT_BUTTON, self.OnClearComment)
        
        comment_bottom_sizer.Add(self.char_count_label, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        comment_bottom_sizer.Add(self.clear_comment_btn, 0, wx.ALL, 5)
        comment_bottom_sizer.Add(self.send_comment_btn, 0, wx.ALL, 5)
        
        new_comment_sizer.Add(comment_bottom_sizer, 0, wx.EXPAND)
        main_sizer.Add(new_comment_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Bind per contatore caratteri
        self.new_comment_ctrl.Bind(wx.EVT_TEXT, self.OnCommentTextChanged)
        
        # Separator finale
        line3 = wx.StaticLine(panel)
        main_sizer.Add(line3, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        
        # Bottoni finali
        final_buttons_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Info URL
        url_label = wx.StaticText(panel, label=f"🔗 {self.pr_data['html_url']}")
        url_label.SetForegroundColour(wx.Colour(0, 0, 255))
        
        # Pulsanti
        self.open_browser_btn = wx.Button(panel, label=_("🌐 Apri nel Browser"))
        self.open_browser_btn.Bind(wx.EVT_BUTTON, self.OnOpenInBrowser)
        
        close_btn = wx.Button(panel, wx.ID_CLOSE, label=_("✖️ Chiudi"))
        close_btn.Bind(wx.EVT_BUTTON, self.OnClose)
        close_btn.SetDefault()
        close_btn.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_CLOSE))
        final_buttons_sizer.Add(url_label, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        final_buttons_sizer.Add(self.open_browser_btn, 0, wx.ALL, 5)
        final_buttons_sizer.Add(close_btn, 0, wx.ALL, 5)
        
        main_sizer.Add(final_buttons_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        panel.SetSizer(main_sizer)
    
    def load_comments(self):
        """Carica i commenti della PR."""
        if not self.github_token:
            self.comments_ctrl.SetValue(_("❌ Token GitHub necessario per visualizzare i commenti."))
            self.send_comment_btn.Enable(False)
            self.comments_count_label.SetLabel(_("Token mancante"))
            return
        
        self.comments_count_label.SetLabel(_("Caricamento..."))
        wx.SafeYield()
        
        headers = {"Authorization": f"Bearer {self.github_token}", "Accept": "application/vnd.github.v3+json"}
        
        # Le PR usano lo stesso endpoint delle issue per i commenti
        comments_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/issues/{self.pr_data['number']}/comments"
        
        try:
            response = requests.get(comments_url, headers=headers, timeout=15)
            response.raise_for_status()
            self.comments_data = response.json()
            
            comment_count = len(self.comments_data)
            self.comments_count_label.SetLabel(f"📊 {comment_count} commenti totali")
            
            if not self.comments_data:
                self.comments_ctrl.SetValue(_("📭 Nessun commento ancora presente.\n\n💡 Scrivi il primo commento usando il campo qui sotto!"))
            else:
                comments_text = ""
                for i, comment in enumerate(self.comments_data):
                    author = comment['user']['login']
                    created_at = comment['created_at'][:16].replace('T', ' ')
                    updated_at = comment.get('updated_at', '')
                    body = comment['body']
                    
                    # Header del commento
                    comments_text += f"{'='*80}\n"
                    comments_text += f"💬 Commento #{i+1} - {author} - {created_at}"
                    
                    if updated_at and updated_at != comment['created_at']:
                        comments_text += f" (modificato: {updated_at[:16].replace('T', ' ')})"
                    
                    comments_text += f"\n{'='*80}\n"
                    comments_text += f"{body}\n\n"
                
                self.comments_ctrl.SetValue(comments_text)
                # Scroll all'inizio
                self.comments_ctrl.SetInsertionPoint(0)
        
        except requests.exceptions.RequestException as e:
            error_msg = f"❌ Errore nel caricare i commenti: {e}"
            self.comments_ctrl.SetValue(error_msg)
            self.send_comment_btn.Enable(False)
            self.comments_count_label.SetLabel(_("Errore caricamento"))
    
    def OnRefreshComments(self, event):
        """Ricarica i commenti."""
        self.load_comments()
    
    def OnCommentTextChanged(self, event):
        """Aggiorna il contatore caratteri."""
        text = self.new_comment_ctrl.GetValue()
        char_count = len(text)
        self.char_count_label.SetLabel(f"{char_count} caratteri")
        
        # Cambia colore se troppo lungo
        if char_count > 65536:  # Limite GitHub
            self.char_count_label.SetForegroundColour(wx.Colour(255, 0, 0))
        else:
            self.char_count_label.SetForegroundColour(wx.Colour(128, 128, 128))
        
        event.Skip()
    
    def OnClearComment(self, event):
        """Pulisce il campo commento."""
        if self.new_comment_ctrl.GetValue().strip():
            dlg = wx.MessageDialog(self, _("Sei sicuro di voler cancellare il commento che stai scrivendo?"), 
                                 _("Conferma Cancellazione"), wx.YES_NO | wx.ICON_QUESTION)
            if dlg.ShowModal() == wx.ID_YES:
                self.new_comment_ctrl.SetValue("")
            dlg.Destroy()
    
    def OnSendComment(self, event):
        """Invia un nuovo commento sulla PR."""
        comment_text = self.new_comment_ctrl.GetValue().strip()
        if not comment_text:
            wx.MessageBox(_("Inserisci un commento prima di inviare."), _("Commento Vuoto"), 
                         wx.OK | wx.ICON_WARNING, self)
            self.new_comment_ctrl.SetFocus()
            return
        
        if len(comment_text) > 65536:
            wx.MessageBox(_("Il commento è troppo lungo (massimo 65536 caratteri)."), 
                         _("Commento Troppo Lungo"), wx.OK | wx.ICON_ERROR, self)
            return
        
        if not self.github_token:
            wx.MessageBox(_("Token GitHub necessario per inviare commenti."), 
                         _("Token Mancante"), wx.OK | wx.ICON_ERROR, self)
            return
        
        # Conferma invio
        confirm_dlg = wx.MessageDialog(self, 
                                     _("Sei sicuro di voler inviare questo commento sulla PR?\n\nIl commento sarà pubblico e visibile a tutti."), 
                                     _("Conferma Invio Commento"), wx.YES_NO | wx.ICON_QUESTION)
        
        if confirm_dlg.ShowModal() != wx.ID_YES:
            confirm_dlg.Destroy()
            return
        confirm_dlg.Destroy()
        
        # Disabilita pulsante durante invio
        self.send_comment_btn.Enable(False)
        self.send_comment_btn.SetLabel(_("📤 Invio..."))
        wx.SafeYield()
        
        headers = {"Authorization": f"Bearer {self.github_token}", "Accept": "application/vnd.github.v3+json"}
        # Le PR usano lo stesso endpoint delle issue per i commenti
        comments_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/issues/{self.pr_data['number']}/comments"
        
        payload = {"body": comment_text}
        
        try:
            response = requests.post(comments_url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            
            wx.MessageBox(_("✅ Commento inviato con successo!"), _("Commento Inviato"), 
                         wx.OK | wx.ICON_INFORMATION, self)
            self.new_comment_ctrl.SetValue("")  # Pulisce il campo
            self.load_comments()  # Ricarica i commenti
            
        except requests.exceptions.RequestException as e:
            wx.MessageBox(f"❌ Errore nell'inviare il commento: {e}", _("Errore Invio"), 
                         wx.OK | wx.ICON_ERROR, self)
        finally:
            # Riabilita pulsante
            self.send_comment_btn.Enable(True)
            self.send_comment_btn.SetLabel(_("📤 Invia Commento"))
    
    def OnOpenInBrowser(self, event):
        """Apre la PR nel browser."""
        try:
            webbrowser.open(self.pr_data['html_url'])
        except Exception as e:
            wx.MessageBox(f"Errore nell'aprire il browser: {e}", "Errore", wx.OK | wx.ICON_ERROR, self)
    
    def OnClose(self, event):
        """Chiude il dialog."""
        # Controlla se c'è testo non salvato
        if self.new_comment_ctrl.GetValue().strip():
            dlg = wx.MessageDialog(self, 
                                 _("Hai un commento non inviato. Sei sicuro di voler chiudere?"), 
                                 _("Commento Non Salvato"), wx.YES_NO | wx.ICON_QUESTION)
            if dlg.ShowModal() != wx.ID_YES:
                dlg.Destroy()
                return
            dlg.Destroy()
        
        self.EndModal(wx.ID_CLOSE)
class CommitSelectionDialog(wx.Dialog):
    def __init__(self, parent, title, repo_path, max_commits=50):
        super(CommitSelectionDialog, self).__init__(parent, title=title, size=(800, 600))
        self.repo_path = repo_path
        self.max_commits = max_commits
        self.selected_commit_hash = None
        
        self.create_ui()
        self.load_commits()
        self.Center()
    
    def create_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Header
        header_label = wx.StaticText(panel, label=_("Seleziona il commit da utilizzare:"))
        header_font = header_label.GetFont()
        header_font.SetWeight(wx.FONTWEIGHT_BOLD)
        header_font.SetPointSize(12)
        header_label.SetFont(header_font)
        main_sizer.Add(header_label, 0, wx.ALL | wx.CENTER, 10)
        
        # Lista commit con dettagli
        self.commits_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        
        # Colonne per la lista
        self.commits_list.AppendColumn(_("Hash"), width=100)
        self.commits_list.AppendColumn(_("Messaggio"), width=350)
        self.commits_list.AppendColumn(_("Autore"), width=150)
        self.commits_list.AppendColumn(_("Data"), width=120)
        self.commits_list.AppendColumn(_("Ref"), width=80)
        
        main_sizer.Add(self.commits_list, 1, wx.ALL | wx.EXPAND, 10)
        
        # Info aggiuntive sul commit selezionato
        info_box = wx.StaticBox(panel, label=_("Dettagli Commit Selezionato"))
        info_sizer = wx.StaticBoxSizer(info_box, wx.VERTICAL)
        
        self.commit_details = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 120))
        self.commit_details.SetBackgroundColour(wx.Colour(250, 250, 250))
        mono_font = wx.Font(9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        if mono_font.IsOk():
            self.commit_details.SetFont(mono_font)
        
        info_sizer.Add(self.commit_details, 1, wx.ALL | wx.EXPAND, 5)
        main_sizer.Add(info_sizer, 0, wx.ALL | wx.EXPAND, 10)
        
        # Status bar per mostrare il numero di commit
        self.status_label = wx.StaticText(panel, label=_("Caricamento commit..."))
        main_sizer.Add(self.status_label, 0, wx.ALL | wx.CENTER, 5)
        
        # Bottoni
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.refresh_btn = wx.Button(panel, label=_("🔄 Aggiorna Lista"))
        self.refresh_btn.Bind(wx.EVT_BUTTON, self.OnRefresh)
        
        self.ok_btn = wx.Button(panel, wx.ID_OK, label=_("✅ Seleziona Commit"))
        self.ok_btn.SetDefault()
        self.ok_btn.Enable(False)  # Disabilitato finché non si seleziona un commit
        
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, label=_("❌ Annulla"))
        
        button_sizer.Add(self.refresh_btn, 0, wx.ALL, 5)
        button_sizer.AddStretchSpacer()
        button_sizer.Add(self.ok_btn, 0, wx.ALL, 5)
        button_sizer.Add(cancel_btn, 0, wx.ALL, 5)
        
        main_sizer.Add(button_sizer, 0, wx.ALL | wx.EXPAND, 10)
        
        # Bind events
        self.commits_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.OnCommitSelected)
        self.commits_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.OnCommitActivated)
        
        panel.SetSizer(main_sizer)
    
    def load_commits(self):
        """Carica la lista dei commit dal repository."""
        self.status_label.SetLabel(_("Caricamento commit in corso..."))
        wx.SafeYield()
        
        process_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        
        try:
            # Comando per ottenere i commit con formato personalizzato
            # Formato: hash|messaggio|autore|data|refs
            cmd = [
                "git", "log", f"-{self.max_commits}",
                "--pretty=format:%h|%s|%an|%ad|%D",
                "--date=short",
                "--all"
            ]
            
            result = subprocess.run(cmd, cwd=self.repo_path, capture_output=True, 
                                  text=True, encoding='utf-8', errors='replace',
                                  creationflags=process_flags)
            
            if result.returncode != 0:
                self.status_label.SetLabel(_("❌ Errore nel recuperare i commit"))
                wx.MessageBox(_("Errore nel recuperare la lista dei commit:\n{}").format(result.stderr), 
                             _("Errore Git"), wx.OK | wx.ICON_ERROR, self)
                return
            
            # Pulisci la lista esistente
            self.commits_list.DeleteAllItems()
            
            # Processa i commit
            commits = []
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    parts = line.split('|')
                    if len(parts) >= 4:
                        hash_short = parts[0]
                        message = parts[1]
                        author = parts[2]
                        date = parts[3]
                        refs = parts[4] if len(parts) > 4 else ""
                        
                        commits.append({
                            'hash': hash_short,
                            'message': message,
                            'author': author,
                            'date': date,
                            'refs': refs
                        })
            
            # Aggiungi i commit alla lista
            for i, commit in enumerate(commits):
                index = self.commits_list.InsertItem(i, commit['hash'])
                self.commits_list.SetItem(index, 1, commit['message'][:80] + ('...' if len(commit['message']) > 80 else ''))
                self.commits_list.SetItem(index, 2, commit['author'])
                self.commits_list.SetItem(index, 3, commit['date'])
                
                # Mostra refs (branch/tag) se presenti
                ref_display = ""
                if commit['refs']:
                    refs_list = [ref.strip() for ref in commit['refs'].split(',') if ref.strip()]
                    if refs_list:
                        ref_display = refs_list[0]  # Mostra solo il primo ref per spazio
                        if len(refs_list) > 1:
                            ref_display += f" (+{len(refs_list)-1})"
                
                self.commits_list.SetItem(index, 4, ref_display)
                
                # Salva i dati completi del commit
                self.commits_list.SetItemData(index, i)
            
            # Salva la lista per riferimento futuro
            self.commits_data = commits
            
            # Aggiorna status
            self.status_label.SetLabel(_("📊 {} commit caricati").format(len(commits)))
            
            # Seleziona automaticamente il primo commit (HEAD)
            if commits:
                self.commits_list.Select(0)
                self.commits_list.Focus(0)
                self.OnCommitSelected(None)
            
        except Exception as e:
            self.status_label.SetLabel(_("❌ Errore nel caricamento"))
            wx.MessageBox(_("Errore imprevisto nel recuperare i commit:\n{}").format(e), 
                         _("Errore"), wx.OK | wx.ICON_ERROR, self)
    
    def OnCommitSelected(self, event):
        """Gestisce la selezione di un commit."""
        selected = self.commits_list.GetFirstSelected()
        if selected == -1:
            self.ok_btn.Enable(False)
            self.commit_details.SetValue("")
            return
        
        # Abilita il pulsante OK
        self.ok_btn.Enable(True)
        
        # Ottieni i dati del commit selezionato
        commit_index = self.commits_list.GetItemData(selected)
        if commit_index < len(self.commits_data):
            commit = self.commits_data[commit_index]
            self.selected_commit_hash = commit['hash']
            
            # Mostra dettagli estesi del commit
            self.show_commit_details(commit['hash'])
    
    def show_commit_details(self, commit_hash):
        """Mostra i dettagli completi del commit selezionato."""
        process_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        
        try:
            # Ottieni dettagli completi del commit
            result = subprocess.run([
                "git", "show", "--no-patch", "--pretty=format:%H%n%s%n%b%n----%nAutore: %an <%ae>%nData: %ad%nCommitter: %cn <%ce>%nData Commit: %cd",
                "--date=local", commit_hash
            ], cwd=self.repo_path, capture_output=True, text=True,
               encoding='utf-8', errors='replace', creationflags=process_flags)
            
            if result.returncode == 0:
                details = result.stdout
                
                # Aggiungi info sui file modificati
                files_result = subprocess.run([
                    "git", "show", "--name-status", "--pretty=format:", commit_hash
                ], cwd=self.repo_path, capture_output=True, text=True,
                   encoding='utf-8', errors='replace', creationflags=process_flags)
                
                if files_result.returncode == 0 and files_result.stdout.strip():
                    details += "\n\n" + _("File modificati:") + "\n"
                    for line in files_result.stdout.strip().split('\n'):
                        if line.strip():
                            details += f"  {line}\n"
                
                self.commit_details.SetValue(details)
            else:
                self.commit_details.SetValue(_("Errore nel recuperare i dettagli del commit."))
                
        except Exception as e:
            self.commit_details.SetValue(_("Errore imprevisto: {}").format(e))
    
    def OnCommitActivated(self, event):
        """Gestisce il doppio click su un commit (equivale a OK)."""
        if self.selected_commit_hash:
            self.EndModal(wx.ID_OK)
    
    def OnRefresh(self, event):
        """Ricarica la lista dei commit."""
        self.load_commits()
    
    def GetSelectedCommitHash(self):
        """Restituisce l'hash del commit selezionato."""
        return self.selected_commit_hash


class GitFrame(wx.Frame):
    def __init__(self, *args, **kw):
        super(GitFrame, self).__init__(*args, **kw)
        self.panel = wx.Panel(self)
        self.git_available = self.check_git_installation()
        self.command_tree_ctrl = None
        self.monitoring_timer = None
        self.monitoring_run_id = None
        self.monitoring_owner = None
        self.monitoring_repo = None
        self.monitoring_start_time = None
        self.monitoring_max_duration = 30 * 60  # 30 minuti
        self.monitoring_poll_count = 0
        self.monitoring_timers = {} # Dizionario per tracciare i timer attivi
        self.github_owner = ""
        self.github_repo = ""
        self.github_token = ""
        self.selected_run_id = None
        self.user_uuid = self._get_or_create_user_uuid()
        self.secure_config_path = self._get_secure_config_path()
        self.app_settings_path = os.path.join(self._get_app_config_dir(), APP_SETTINGS_FILE_NAME)
        self.github_ask_pass_on_startup = True
        self.github_strip_log_timestamps = False
        self.github_monitoring_beep = True
        self._last_processed_path_for_context = None # Usato per tracciare l'ultimo path processato
        self.InitUI()
        self.SetMinSize((800, 700))
        self.Centre()
        self.SetTitle(_("Assistente Git Semplice v1.1"))
        self.Show(True)
        print("DEBUG: secure_config_path finale =", self.secure_config_path)
        self._load_app_settings() # Carica le opzioni non sensibili
        github_config_loaded_at_startup = False
        if self.github_ask_pass_on_startup:
            if os.path.exists(self.secure_config_path):
                if self._prompt_and_load_github_config(called_from_startup=True):
                    github_config_loaded_at_startup = True
        else:
            self.output_text_ctrl.AppendText(_("Richiesta password all'avvio per GitHub disabilitata. Il token (se salvato) non è stato caricato.\n"))
            if os.path.exists(self.secure_config_path):
                 if self._ensure_github_config_loaded(): # Questo tenterà con password vuota
                    github_config_loaded_at_startup = True
        self._update_github_context_from_path()
        if not self.git_available:
            self._handle_git_not_found()
            if self.command_tree_ctrl: self.command_tree_ctrl.Disable()
        else:
            if self.command_tree_ctrl:
                   wx.CallAfter(self.command_tree_ctrl.SetFocus)

        self.Bind(wx.EVT_CHAR_HOOK, self.OnCharHook)
        self.Bind(wx.EVT_CLOSE, self.OnClose)



    def handle_list_issues(self, command_name_key, command_details):
        """Gestisce la visualizzazione delle issue del repository"""
        if not self.github_owner or not self.github_repo:
            self.output_text_ctrl.AppendText(_("ERRORE: Repository GitHub non configurato.\n"))
            return

        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"

        # Dialog per filtri
        filter_dlg = wx.Dialog(self, title=_("Filtri per Issue"), size=(400, 300))
        panel = wx.Panel(filter_dlg)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Stato
        state_label = wx.StaticText(panel, label=_("Stato:"))
        state_choice = wx.Choice(panel, choices=[_("Tutte"), _("Aperte"), _("Chiuse")])
        state_choice.SetSelection(1)  # Default: Aperte
        sizer.Add(state_label, 0, wx.ALL, 5)
        sizer.Add(state_choice, 0, wx.EXPAND | wx.ALL, 5)

        # Labels
        labels_label = wx.StaticText(panel, label=_("Filtra per Label (opzionale):"))
        labels_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE, size=(-1, 80))
        labels_ctrl.SetHint(_("bug,enhancement,help wanted\n(separati da virgola)"))
        sizer.Add(labels_label, 0, wx.ALL, 5)
        sizer.Add(labels_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        # Bottoni
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        ok_btn = wx.Button(panel, wx.ID_OK, _("Carica Issue"))
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Annulla"))
        btn_sizer.Add(ok_btn, 0, wx.ALL, 5)
        btn_sizer.Add(cancel_btn, 0, wx.ALL, 5)
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        panel.SetSizer(sizer)
        filter_dlg.Fit()

        if filter_dlg.ShowModal() != wx.ID_OK:
            self.output_text_ctrl.AppendText(_("Visualizzazione issue annullata.\n"))
            filter_dlg.Destroy()
            return

        # Ottieni parametri filtro
        state_map = {0: "all", 1: "open", 2: "closed"}
        state = state_map[state_choice.GetSelection()]
        labels_text = labels_ctrl.GetValue().strip()
        
        filter_dlg.Destroy()

        # Chiamata API
        issues_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/issues"
        params = {"state": state, "per_page": 50, "sort": "updated", "direction": "desc"}
        
        if labels_text:
            params["labels"] = labels_text

        self.output_text_ctrl.AppendText(_("🔍 Recupero issue per {}/{}...\n").format(self.github_owner, self.github_repo))
        wx.Yield()

        try:
            response = requests.get(issues_url, headers=headers, params=params, timeout=15)
            response.raise_for_status()
            issues_data = response.json()

            # Filtra le PR (GitHub API include le PR nelle issue)
            actual_issues = [issue for issue in issues_data if "pull_request" not in issue]

            if not actual_issues:
                self.output_text_ctrl.AppendText(_("Nessuna issue trovata con i filtri specificati.\n"))
                return

            # Mostra le issue in un dialog di selezione
            issue_choices = []
            issue_map = {}
            
            for issue in actual_issues:
                state_icon = "🟢" if issue["state"] == "open" else "🔴"
                assignee_text = f"→ {issue['assignee']['login']}" if issue.get('assignee') else "→ Non assegnata"
                labels_text = ", ".join([label['name'] for label in issue.get('labels', [])])
                labels_display = f" [{labels_text}]" if labels_text else ""
                
                choice_str = f"{state_icon} #{issue['number']}: {issue['title'][:60]}... {assignee_text}{labels_display}"
                issue_choices.append(choice_str)
                issue_map[choice_str] = issue

            select_dlg = wx.SingleChoiceDialog(self, 
                                             _("Seleziona una issue per vedere i dettagli:"),
                                             _("Issue di {}/{}").format(self.github_owner, self.github_repo),
                                             issue_choices,
                                             wx.CHOICEDLG_STYLE)

            if select_dlg.ShowModal() == wx.ID_OK:
                print("L'utente ha cliccato su ok.")
                selected_choice = select_dlg.GetStringSelection()
                selected_issue = issue_map.get(selected_choice)
                if selected_issue:
                    # Apri dialog di gestione issue
                    issue_dialog = IssueManagementDialog(
                        self, selected_issue, self.github_owner, self.github_repo, self.github_token
                    )
                    issue_dialog.ShowModal()
                    issue_dialog.Destroy()
            else:
                self.output_text_ctrl.AppendText(_("Nessuna issue selezionata.\n"))
            
            select_dlg.Destroy()

        except requests.exceptions.RequestException as e:
            self.output_text_ctrl.AppendText(_("❌ Errore durante il recupero delle issue: {}\n").format(e))
    def HandleCheckoutWithLocalChanges(self, repo_path, target_commit, original_stderr):
        """Gestisce il caso in cui checkout fallisce per modifiche locali non committate."""
        
        self.output_text_ctrl.AppendText(
            _("\n*** CHECKOUT BLOCCATO: Modifiche locali non committate rilevate! ***\n")
        )
        
        # Estrai i file in conflitto dall'errore
        conflicting_files = []
        lines = original_stderr.split('\n')
        capture_files = False
        
        for line in lines:
            line = line.strip()
            if "would be overwritten by checkout:" in line:
                capture_files = True
                continue
            elif capture_files and line and not line.startswith("Please commit"):
                if line.startswith('\t'):
                    file_path = line.strip('\t').strip()
                    if file_path:
                        conflicting_files.append(file_path)
                else:
                    break
        
        if conflicting_files:
            self.output_text_ctrl.AppendText(_("File con modifiche locali che impediscono il checkout:\n"))
            for file_path in conflicting_files[:10]:  # Mostra primi 10
                self.output_text_ctrl.AppendText(f"  📝 {file_path}\n")
            if len(conflicting_files) > 10:
                self.output_text_ctrl.AppendText(f"  ... e altri {len(conflicting_files) - 10} file\n")
            self.output_text_ctrl.AppendText("\n")
        
        # Opzioni per risolvere il problema
        dialog_message = _(
            "Il checkout al commit '{}' è stato bloccato perché ci sono modifiche locali non committate.\n\n"
            "Come vuoi procedere?\n\n"
            "💡 Spiegazione opzioni:\n"
            "• STASH: Salva temporaneamente le modifiche (potrai recuperarle dopo)\n"
            "• COMMIT: Crea un commit con le modifiche attuali\n"
            "• SCARTA: Elimina definitivamente le modifiche locali (IRREVERSIBILE!)\n"
            "• ANNULLA: Non fare nulla e tornare allo stato attuale"
        ).format(target_commit)
        
        choices = [
            _("💾 STASH - Salva modifiche temporaneamente e procedi con checkout"),
            _("📝 COMMIT - Committa le modifiche e procedi con checkout"),
            _("🗑️ SCARTA - Elimina modifiche locali e procedi con checkout (IRREVERSIBILE!)"),
            _("❌ ANNULLA - Non fare checkout e mantenere modifiche locali")
        ]
        
        choice_dlg = wx.SingleChoiceDialog(
            self, 
            dialog_message, 
            _("Risolvi Conflitto Checkout"), 
            choices, 
            wx.CHOICEDLG_STYLE
        )
        
        if choice_dlg.ShowModal() == wx.ID_OK:
            strategy_choice_text = choice_dlg.GetStringSelection()
            self.output_text_ctrl.AppendText(_("Strategia scelta: {}\n").format(strategy_choice_text))
            
            success = False
            
            if strategy_choice_text == choices[0]:  # STASH
                self.output_text_ctrl.AppendText(_("📦 Salvataggio modifiche in stash...\n"))
                wx.Yield()
                
                if self.RunSingleGitCommand(["git", "stash", "push", "-m", f"Auto-stash before checkout to {target_commit}"], 
                                           repo_path, _("Stash modifiche automatico")):
                    self.output_text_ctrl.AppendText(_("✅ Modifiche salvate in stash.\n"))
                    success = True
                else:
                    self.output_text_ctrl.AppendText(_("❌ Errore nel salvare le modifiche in stash.\n"))
                    
            elif strategy_choice_text == choices[1]:  # COMMIT
                # Chiedi messaggio di commit
                commit_dlg = InputDialog(
                    self, 
                    _("Commit Modifiche"), 
                    _("Inserisci il messaggio per il commit delle modifiche attuali:"),
                    _("WIP: Salvataggio modifiche prima di checkout")
                )
                
                if commit_dlg.ShowModal() == wx.ID_OK:
                    commit_message = commit_dlg.GetValue()
                    if not commit_message.strip():
                        commit_message = f"Auto-commit before checkout to {target_commit}"
                    
                    self.output_text_ctrl.AppendText(_("📝 Creazione commit con modifiche attuali...\n"))
                    wx.Yield()
                    
                    # Prima aggiungi tutte le modifiche
                    if self.RunSingleGitCommand(["git", "add", "."], repo_path, _("Aggiungi modifiche per commit")):
                        # Poi committa
                        if self.RunSingleGitCommand(["git", "commit", "-m", commit_message], 
                                                   repo_path, _("Commit modifiche automatico")):
                            self.output_text_ctrl.AppendText(_("✅ Commit creato con successo.\n"))
                            success = True
                        else:
                            self.output_text_ctrl.AppendText(_("❌ Errore nella creazione del commit.\n"))
                    else:
                        self.output_text_ctrl.AppendText(_("❌ Errore nell'aggiungere le modifiche.\n"))
                else:
                    self.output_text_ctrl.AppendText(_("Commit annullato dall'utente.\n"))
                
                commit_dlg.Destroy()
                
            elif strategy_choice_text == choices[2]:  # SCARTA
                # Conferma aggiuntiva per azione irreversibile
                confirm_msg = _(
                    "⚠️ ATTENZIONE MASSIMA! ⚠️\n\n"
                    "Stai per ELIMINARE DEFINITIVAMENTE tutte le modifiche locali non committate.\n"
                    "Questa azione è IRREVERSIBILE!\n\n"
                    "File che verranno resettati:\n{}\n\n"
                    "Sei ASSOLUTAMENTE SICURO di voler procedere?"
                ).format('\n'.join([f"• {f}" for f in conflicting_files[:5]]) + 
                        (f"\n• ... e altri {len(conflicting_files) - 5} file" if len(conflicting_files) > 5 else ""))
                
                confirm_dlg = wx.MessageDialog(
                    self, 
                    confirm_msg, 
                    _("CONFERMA ELIMINAZIONE MODIFICHE"), 
                    wx.YES_NO | wx.NO_DEFAULT | wx.ICON_ERROR
                )
                
                if confirm_dlg.ShowModal() == wx.ID_YES:
                    self.output_text_ctrl.AppendText(_("🗑️ Eliminazione modifiche locali...\n"))
                    wx.Yield()
                    
                    # Reset hard + clean per eliminare tutto
                    if self.RunSingleGitCommand(["git", "reset", "--hard", "HEAD"], 
                                               repo_path, _("Reset modifiche locali")):
                        if self.RunSingleGitCommand(["git", "clean", "-fd"], 
                                                   repo_path, _("Pulizia file non tracciati")):
                            self.output_text_ctrl.AppendText(_("✅ Modifiche locali eliminate.\n"))
                            success = True
                        else:
                            self.output_text_ctrl.AppendText(_("❌ Errore nella pulizia dei file non tracciati.\n"))
                            success = True  # Reset è riuscito, continua comunque
                    else:
                        self.output_text_ctrl.AppendText(_("❌ Errore nel reset delle modifiche.\n"))
                else:
                    self.output_text_ctrl.AppendText(_("Eliminazione modifiche annullata dall'utente.\n"))
                
                confirm_dlg.Destroy()
                
            else:  # ANNULLA
                self.output_text_ctrl.AppendText(_("Checkout annullato. Modifiche locali mantenute.\n"))
                choice_dlg.Destroy()
                return False
            
            # Se la strategia ha avuto successo, prova di nuovo il checkout
            if success:
                self.output_text_ctrl.AppendText(_("\n🔄 Tentativo checkout dopo risoluzione conflitti...\n"))
                wx.Yield()
                
                if self.RunSingleGitCommand(["git", "checkout", target_commit], 
                                           repo_path, f"Checkout a {target_commit} (post-risoluzione)"):
                    self.output_text_ctrl.AppendText(_("✅ Checkout completato con successo!\n"))
                    
                    # Se abbiamo fatto stash, ricorda all'utente
                    if strategy_choice_text == choices[0]:
                        self.output_text_ctrl.AppendText(
                            _("\n💡 Le tue modifiche sono salvate in stash.\n"
                              "Usa '{}' per recuperarle quando necessario.\n").format(CMD_STASH_POP)
                        )
                    
                    choice_dlg.Destroy()
                    return True
                else:
                    self.output_text_ctrl.AppendText(_("❌ Checkout fallito anche dopo la risoluzione dei conflitti.\n"))
            
        else:
            self.output_text_ctrl.AppendText(_("Risoluzione conflitti annullata dall'utente.\n"))
        
        choice_dlg.Destroy()
        return False

    def handle_edit_issue(self, command_name_key, command_details):
        """Gestisce la modifica di una issue esistente"""
        if not self.github_owner or not self.github_repo or not self.github_token:
            self.output_text_ctrl.AppendText(_("ERRORE: Repository GitHub e token non configurati.\n"))
            return

        headers = {"Authorization": f"Bearer {self.github_token}", "Accept": "application/vnd.github.v3+json"}
        
        # Prima, carica le issue aperte
        issues_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/issues"
        params = {"state": "open", "per_page": 30}

        try:
            response = requests.get(issues_url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            issues_data = response.json()
            
            actual_issues = [issue for issue in issues_data if "pull_request" not in issue]
            
            if not actual_issues:
                self.output_text_ctrl.AppendText(_("Nessuna issue aperta trovata da modificare.\n"))
                return

            # Selezione issue da modificare
            issue_choices = [f"#{issue['number']}: {issue['title']}" for issue in actual_issues]
            issue_map = {choice: issue for choice, issue in zip(issue_choices, actual_issues)}

            select_dlg = wx.SingleChoiceDialog(self, 
                                             _("Seleziona la issue da modificare:"),
                                             _("Modifica Issue"),
                                             issue_choices,
                                             wx.CHOICEDLG_STYLE)

            if select_dlg.ShowModal() != wx.ID_OK:
                self.output_text_ctrl.AppendText(_("Modifica issue annullata.\n"))
                select_dlg.Destroy()
                return

            selected_issue = issue_map[select_dlg.GetStringSelection()]
            select_dlg.Destroy()

            # Dialog di modifica
            edit_dlg = CreateIssueDialog(self, _("Modifica Issue"), 
                                       self.get_repository_labels(), 
                                       self.get_repository_collaborators())
            
            # Pre-popola con dati esistenti
            edit_dlg.title_ctrl.SetValue(selected_issue['title'])
            edit_dlg.desc_ctrl.SetValue(selected_issue['body'] or "")
            
            # Pre-seleziona labels esistenti
            existing_labels = [label['name'] for label in selected_issue.get('labels', [])]
            for i in range(edit_dlg.labels_checklist.GetCount()):
                if edit_dlg.labels_list[i] in existing_labels:
                    edit_dlg.labels_checklist.Check(i)

            if edit_dlg.ShowModal() == wx.ID_OK:
                values = edit_dlg.GetValues()
                
                # Prepara payload per aggiornamento
                update_payload = {
                    "title": values["title"],
                    "body": values["body"],
                    "labels": values["labels"],
                    "assignees": values["assignees"]
                }

                # Aggiorna issue via API
                update_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/issues/{selected_issue['number']}"
                
                self.output_text_ctrl.AppendText(_("🔄 Aggiornamento issue #{}...\n").format(selected_issue['number']))
                wx.Yield()

                update_response = requests.patch(update_url, headers=headers, json=update_payload, timeout=15)
                update_response.raise_for_status()
                
                updated_issue = update_response.json()
                self.output_text_ctrl.AppendText(_("✅ Issue #{} aggiornata con successo!\n").format(updated_issue['number']))
                self.output_text_ctrl.AppendText(_("🔗 URL: {}\n").format(updated_issue['html_url']))

            edit_dlg.Destroy()

        except requests.exceptions.RequestException as e:
            self.output_text_ctrl.AppendText(_("❌ Errore durante la modifica: {}\n").format(e))

    def handle_delete_issue(self, command_name_key, command_details):
        """Gestisce la chiusura di una issue"""
        if not self.github_owner or not self.github_repo or not self.github_token:
            self.output_text_ctrl.AppendText(_("ERRORE: Repository GitHub e token non configurati.\n"))
            return

        headers = {"Authorization": f"Bearer {self.github_token}", "Accept": "application/vnd.github.v3+json"}
        
        # Carica issue aperte
        issues_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/issues"
        params = {"state": "open", "per_page": 50}

        try:
            response = requests.get(issues_url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            issues_data = response.json()
            
            actual_issues = [issue for issue in issues_data if "pull_request" not in issue]
            
            if not actual_issues:
                self.output_text_ctrl.AppendText(_("Nessuna issue aperta trovata da chiudere.\n"))
                return

            # Selezione issue da chiudere
            issue_choices = [f"#{issue['number']}: {issue['title']}" for issue in actual_issues]
            issue_map = {choice: issue for choice, issue in zip(issue_choices, actual_issues)}

            select_dlg = wx.SingleChoiceDialog(self, 
                                             _("Seleziona la issue da chiudere:"),
                                             _("Chiudi Issue"),
                                             issue_choices,
                                             wx.CHOICEDLG_STYLE)

            if select_dlg.ShowModal() != wx.ID_OK:
                self.output_text_ctrl.AppendText(_("Chiusura issue annullata.\n"))
                select_dlg.Destroy()
                return

            selected_issue = issue_map[select_dlg.GetStringSelection()]
            select_dlg.Destroy()

            # Conferma chiusura
            confirm_msg = _("Sei sicuro di voler chiudere la issue:\n\n#{}: {}\n\nQuesta azione può essere annullata riaprendo la issue su GitHub.").format(
                selected_issue['number'], selected_issue['title']
            )
            
            confirm_dlg = wx.MessageDialog(self, confirm_msg, _("Conferma Chiusura Issue"), 
                                         wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)

            if confirm_dlg.ShowModal() != wx.ID_YES:
                self.output_text_ctrl.AppendText(_("Chiusura issue annullata.\n"))
                confirm_dlg.Destroy()
                return
            
            confirm_dlg.Destroy()

            # Chiudi issue via API
            close_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/issues/{selected_issue['number']}"
            close_payload = {"state": "closed"}

            self.output_text_ctrl.AppendText(_("🔒 Chiusura issue #{}...\n").format(selected_issue['number']))
            wx.Yield()

            close_response = requests.patch(close_url, headers=headers, json=close_payload, timeout=15)
            close_response.raise_for_status()
            
            self.output_text_ctrl.AppendText(_("✅ Issue #{} chiusa con successo!\n").format(selected_issue['number']))

        except requests.exceptions.RequestException as e:
            self.output_text_ctrl.AppendText(_("❌ Errore durante la chiusura: {}\n").format(e))

    def handle_list_prs(self, command_name_key, command_details):
        """Gestisce la visualizzazione delle Pull Request del repository"""
        if not self.github_owner or not self.github_repo:
            self.output_text_ctrl.AppendText(_("ERRORE: Repository GitHub non configurato.\n"))
            return

        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"

        # Dialog per filtri
        filter_dlg = wx.Dialog(self, title=_("Filtri per Pull Request"), size=(400, 200))
        panel = wx.Panel(filter_dlg)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Stato
        state_label = wx.StaticText(panel, label=_("Stato:"))
        state_choice = wx.Choice(panel, choices=[_("Tutte"), _("Aperte"), _("Chiuse"), _("Mergiate")])
        state_choice.SetSelection(1)  # Default: Aperte
        sizer.Add(state_label, 0, wx.ALL, 5)
        sizer.Add(state_choice, 0, wx.EXPAND | wx.ALL, 5)

        # Bottoni
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        ok_btn = wx.Button(panel, wx.ID_OK, _("Carica PR"))
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Annulla"))
        btn_sizer.Add(ok_btn, 0, wx.ALL, 5)
        btn_sizer.Add(cancel_btn, 0, wx.ALL, 5)
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        panel.SetSizer(sizer)
        filter_dlg.Fit()

        if filter_dlg.ShowModal() != wx.ID_OK:
            self.output_text_ctrl.AppendText(_("Visualizzazione PR annullata.\n"))
            filter_dlg.Destroy()
            return

        # Ottieni parametri filtro
        state_map = {0: "all", 1: "open", 2: "closed", 3: "all"}  # Mergiate vengono filtrate dopo
        state = state_map[state_choice.GetSelection()]
        show_merged_only = state_choice.GetSelection() == 3
        
        filter_dlg.Destroy()

        # Chiamata API
        prs_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/pulls"
        params = {"state": state, "per_page": 50, "sort": "updated", "direction": "desc"}

        self.output_text_ctrl.AppendText(_("🔍 Recupero Pull Request per {}/{}...\n").format(self.github_owner, self.github_repo))
        wx.Yield()

        try:
            response = requests.get(prs_url, headers=headers, params=params, timeout=15)
            response.raise_for_status()
            prs_data = response.json()

            # Filtra per stato merged se richiesto
            if show_merged_only:
                prs_data = [pr for pr in prs_data if pr.get('merged_at') is not None]

            if not prs_data:
                self.output_text_ctrl.AppendText(_("Nessuna Pull Request trovata con i filtri specificati.\n"))
                return

            # Mostra le PR in un dialog di selezione
            pr_choices = []
            pr_map = {}
            
            for pr in prs_data:
                if pr.get('merged_at'):
                    state_icon = "🟣"  # Merged
                    state_text = "MERGED"
                elif pr["state"] == "open":
                    state_icon = "🟢"  # Open
                    state_text = "OPEN"
                else:
                    state_icon = "🔴"  # Closed
                    state_text = "CLOSED"
                
                draft_text = " [DRAFT]" if pr.get('draft', False) else ""
                choice_str = f"{state_icon} #{pr['number']}: {pr['title'][:50]}... ({pr['head']['ref']} → {pr['base']['ref']}){draft_text}"
                pr_choices.append(choice_str)
                pr_map[choice_str] = pr

            select_dlg = wx.SingleChoiceDialog(self, 
                                             _("Seleziona una PR per vedere i dettagli:"),
                                             _("Pull Request di {}/{}").format(self.github_owner, self.github_repo),
                                             pr_choices,
                                             wx.CHOICEDLG_STYLE)

            if select_dlg.ShowModal() == wx.ID_OK:
                selected_choice = select_dlg.GetStringSelection()
                selected_pr = pr_map.get(selected_choice)
                if selected_pr:
                    # Apri dialog di gestione PR
                    pr_dialog = PullRequestManagementDialog(
                        self, selected_pr, self.github_owner, self.github_repo, self.github_token
                    )
                    pr_dialog.ShowModal()
                    pr_dialog.Destroy()                
            else:
                self.output_text_ctrl.AppendText(_("Nessuna PR selezionata.\n"))
            
            select_dlg.Destroy()

        except requests.exceptions.RequestException as e:
            self.output_text_ctrl.AppendText(_("❌ Errore durante il recupero delle PR: {}\n").format(e))
    def ShowSuccessNotification(self, title, message, details=None):
        """Mostra una notifica di successo con opzione per dettagli."""
        
        # Icona e colori per successo
        icon = wx.ICON_INFORMATION
        
        # Messaggio base
        display_message = f"✅ {message}"
        
        # Se ci sono dettagli, offri opzione per vederli
        if details and len(details.strip()) > 0:
            display_message += _("\n\nVuoi vedere i dettagli dell'operazione?")
            
            dlg = wx.MessageDialog(
                self, 
                display_message, 
                f"🎉 {title}", 
                wx.YES_NO | wx.ICON_INFORMATION
            )
            
            dlg.SetYesNoLabels(_("📋 Vedi Dettagli"), _("👍 OK"))
            
            response = dlg.ShowModal()
            dlg.Destroy()
            
            if response == wx.ID_YES:
                # Mostra dettagli in una finestra separata
                self.ShowDetailsDialog(title, message, details, is_success=True)
        else:
            # Notifica semplice senza dettagli
            wx.MessageBox(
                display_message,
                f"🎉 {title}",
                wx.OK | icon,
                self
            )

    def ShowErrorNotification(self, title, message, details=None, suggestions=None):
        """Mostra una notifica di errore con dettagli e suggerimenti opzionali."""
        
        # Messaggio base
        display_message = f"❌ {message}"
        
        # Aggiungi suggerimenti se presenti
        if suggestions:
            display_message += f"\n\n💡 {suggestions}"
        
        # Se ci sono dettagli, offri opzione per vederli
        if details and len(details.strip()) > 0:
            display_message += _("\n\nVuoi vedere i dettagli dell'errore per diagnosticare il problema?")
            
            dlg = wx.MessageDialog(
                self, 
                display_message, 
                f"💥 {title}", 
                wx.YES_NO | wx.ICON_ERROR
            )
            
            dlg.SetYesNoLabels(_("🔍 Vedi Dettagli"), _("😞 Chiudi"))
            
            response = dlg.ShowModal()
            dlg.Destroy()
            
            if response == wx.ID_YES:
                # Mostra dettagli in una finestra separata
                self.ShowDetailsDialog(title, message, details, is_success=False, suggestions=suggestions)
        else:
            # Notifica semplice senza dettagli
            wx.MessageBox(
                display_message,
                f"💥 {title}",
                wx.OK | wx.ICON_ERROR,
                self
            )

    def ShowDetailsDialog(self, title, message, details, is_success=True, suggestions=None):
        """Mostra una finestra di dettagli espandibile."""
        
        # Crea dialog personalizzato
        dlg = wx.Dialog(self, title=f"{'🎉' if is_success else '💥'} {title} - Dettagli", size=(600, 450))
        panel = wx.Panel(dlg)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Header con messaggio principale
        header_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Icona grande
        icon_label = wx.StaticText(panel, label="✅" if is_success else "❌")
        icon_font = icon_label.GetFont()
        icon_font.SetPointSize(24)
        icon_label.SetFont(icon_font)
        
        # Messaggio principale
        message_label = wx.StaticText(panel, label=message)
        message_font = message_label.GetFont()
        message_font.SetWeight(wx.FONTWEIGHT_BOLD)
        message_font.SetPointSize(12)
        message_label.SetFont(message_font)
        
        header_sizer.Add(icon_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 15)
        header_sizer.Add(message_label, 1, wx.ALIGN_CENTER_VERTICAL)
        
        main_sizer.Add(header_sizer, 0, wx.ALL | wx.EXPAND, 15)
        
        # Separator
        line = wx.StaticLine(panel)
        main_sizer.Add(line, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 15)
        
        # Area dettagli
        details_label = wx.StaticText(panel, label=_("📋 Dettagli tecnici:"))
        details_font = details_label.GetFont()
        details_font.SetWeight(wx.FONTWEIGHT_BOLD)
        details_label.SetFont(details_font)
        main_sizer.Add(details_label, 0, wx.ALL, 15)
        
        # Text area per dettagli
        details_text = wx.TextCtrl(panel, value=details, style=wx.TE_MULTILINE | wx.TE_READONLY)
        details_text.SetBackgroundColour(wx.Colour(248, 248, 248))
        
        # Font monospazio per output tecnico
        mono_font = wx.Font(9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        if mono_font.IsOk():
            details_text.SetFont(mono_font)
        
        main_sizer.Add(details_text, 1, wx.ALL | wx.EXPAND, 15)
        
        # Suggerimenti se presenti
        if suggestions:
            suggestions_label = wx.StaticText(panel, label=_("💡 Suggerimenti:"))
            suggestions_font = suggestions_label.GetFont()
            suggestions_font.SetWeight(wx.FONTWEIGHT_BOLD)
            suggestions_label.SetFont(suggestions_font)
            main_sizer.Add(suggestions_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 15)
            
            suggestions_text = wx.StaticText(panel, label=suggestions)
            suggestions_text.Wrap(550)
            main_sizer.Add(suggestions_text, 0, wx.ALL | wx.EXPAND, 15)
        
        # Bottoni
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        copy_btn = wx.Button(panel, label=_("📋 Copia Dettagli"))
        copy_btn.Bind(wx.EVT_BUTTON, lambda e: self.CopyToClipboard(details))
        
        close_btn = wx.Button(panel, wx.ID_CLOSE, label=_("✖️ Chiudi"))
        close_btn.SetDefault()
        close_btn.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_CLOSE))
        btn_sizer.Add(copy_btn, 0, wx.RIGHT, 10)
        btn_sizer.AddStretchSpacer()
        btn_sizer.Add(close_btn, 0)
        
        main_sizer.Add(btn_sizer, 0, wx.ALL | wx.EXPAND, 15)
        
        panel.SetSizer(main_sizer)
        dlg.Center()
        dlg.ShowModal()
        dlg.Destroy()
    def CopyToClipboard(self, text, parent_dialog=None):
        """Copia testo negli appunti con dialogo di conferma accessibile."""
        try:
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(text))
                wx.TheClipboard.Close()
                
                # Usa sempre il frame principale (self) come parent per evitare problemi
                wx.CallAfter(self.ShowCopyMessage, True)
                
        except Exception as e:
            # Usa sempre il frame principale anche per gli errori
            wx.CallAfter(self.ShowCopyMessage, False)

    def ShowOperationResult(self, operation_name, success, output="", error_output="", suggestions=None):
        """Metodo unificato per mostrare risultato di qualsiasi operazione."""
        
        if success:
            # Estrai info utili dall'output per il messaggio
            if "commit" in operation_name.lower():
                if "commit" in output.lower() and len(output.strip()) > 0:
                    lines = output.strip().split('\n')
                    commit_line = next((line for line in lines if 'commit' in line.lower()), None)
                    if commit_line:
                        message = _("Commit creato con successo!")
                        details = output
                    else:
                        message = _("Operazione completata!")
                        details = output
                else:
                    message = _("Operazione completata!")
                    details = output
            elif "push" in operation_name.lower():
                message = _("Push completato con successo!")
                details = output
            elif "pull" in operation_name.lower():
                message = _("Pull completato con successo!")
                details = output
            elif "checkout" in operation_name.lower():
                message = _("Checkout completato con successo!")
                details = output
            elif "merge" in operation_name.lower():
                message = _("Merge completato con successo!")
                details = output
            else:
                message = _("Operazione completata con successo!")
                details = output
            
            self.ShowSuccessNotification(
                title=_("Successo - {}").format(operation_name),
                message=message,
                details=details if details.strip() else None
            )
        else:
            # Gestione errori con suggerimenti specifici
            if "push" in operation_name.lower() and "rejected" in error_output.lower():
                error_message = _("Push rifiutato dal server remoto.")
                suggestions = _("Prova a fare 'pull' prima per sincronizzare le modifiche remote.")
            elif "commit" in operation_name.lower() and "nothing to commit" in error_output.lower():
                error_message = _("Nulla da committare.")
                suggestions = _("Non ci sono modifiche da salvare. Modifica alcuni file prima di committare.")
            elif "checkout" in operation_name.lower() and "pathspec" in error_output.lower():
                error_message = _("Branch o commit non trovato.")
                suggestions = _("Verifica che il nome del branch/commit sia corretto.")
            elif "merge" in operation_name.lower() and "conflict" in error_output.lower():
                error_message = _("Conflitti di merge rilevati.")
                suggestions = _("Risolvi i conflitti manualmente o usa le opzioni automatiche proposte.")
            else:
                error_message = _("Operazione fallita.")
                suggestions = suggestions  # Usa suggerimenti passati o None
            
            self.ShowErrorNotification(
                title=_("Errore - {}").format(operation_name),
                message=error_message,
                details=error_output if error_output.strip() else output,
                suggestions=suggestions
            )

    def handle_edit_pr(self, command_name_key, command_details):
        """Gestisce la modifica di una Pull Request esistente"""
        if not self.github_owner or not self.github_repo or not self.github_token:
            self.output_text_ctrl.AppendText(_("ERRORE: Repository GitHub e token non configurati.\n"))
            return

        headers = {"Authorization": f"Bearer {self.github_token}", "Accept": "application/vnd.github.v3+json"}
        
        # Carica PR aperte
        prs_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/pulls"
        params = {"state": "open", "per_page": 30}

        try:
            response = requests.get(prs_url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            prs_data = response.json()
            
            if not prs_data:
                self.output_text_ctrl.AppendText(_("Nessuna Pull Request aperta trovata da modificare.\n"))
                return

            # Selezione PR da modificare
            pr_choices = [f"#{pr['number']}: {pr['title']} ({pr['head']['ref']} → {pr['base']['ref']})" for pr in prs_data]
            pr_map = {choice: pr for choice, pr in zip(pr_choices, prs_data)}

            select_dlg = wx.SingleChoiceDialog(self, 
                                             _("Seleziona la PR da modificare:"),
                                             _("Modifica Pull Request"),
                                             pr_choices,
                                             wx.CHOICEDLG_STYLE)

            if select_dlg.ShowModal() != wx.ID_OK:
                self.output_text_ctrl.AppendText(_("Modifica PR annullata.\n"))
                select_dlg.Destroy()
                return

            selected_pr = pr_map[select_dlg.GetStringSelection()]
            select_dlg.Destroy()

            # Dialog di modifica semplificato
            edit_dlg = wx.Dialog(self, title=_("Modifica Pull Request"), size=(500, 400))
            panel = wx.Panel(edit_dlg)
            sizer = wx.BoxSizer(wx.VERTICAL)

            # Titolo
            title_label = wx.StaticText(panel, label=_("Titolo:"))
            title_ctrl = wx.TextCtrl(panel, value=selected_pr['title'])
            sizer.Add(title_label, 0, wx.ALL, 5)
            sizer.Add(title_ctrl, 0, wx.EXPAND | wx.ALL, 5)

            # Descrizione
            desc_label = wx.StaticText(panel, label=_("Descrizione:"))
            desc_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE, value=selected_pr['body'] or "")
            sizer.Add(desc_label, 0, wx.ALL, 5)
            sizer.Add(desc_ctrl, 1, wx.EXPAND | wx.ALL, 5)

            # Draft checkbox
            draft_cb = wx.CheckBox(panel, label=_("Draft"))
            draft_cb.SetValue(selected_pr.get('draft', False))
            sizer.Add(draft_cb, 0, wx.ALL, 5)

            # Bottoni
            btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
            ok_btn = wx.Button(panel, wx.ID_OK, _("Aggiorna"))
            cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Annulla"))
            btn_sizer.Add(ok_btn, 0, wx.ALL, 5)
            btn_sizer.Add(cancel_btn, 0, wx.ALL, 5)
            sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)

            panel.SetSizer(sizer)

            if edit_dlg.ShowModal() == wx.ID_OK:
                # Prepara payload per aggiornamento
                update_payload = {
                    "title": title_ctrl.GetValue(),
                    "body": desc_ctrl.GetValue(),
                    "draft": draft_cb.GetValue()
                }

                # Aggiorna PR via API
                update_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/pulls/{selected_pr['number']}"
                
                self.output_text_ctrl.AppendText(_("🔄 Aggiornamento PR #{}...\n").format(selected_pr['number']))
                wx.Yield()

                update_response = requests.patch(update_url, headers=headers, json=update_payload, timeout=15)
                update_response.raise_for_status()
                
                updated_pr = update_response.json()
                self.output_text_ctrl.AppendText(_("✅ PR #{} aggiornata con successo!\n").format(updated_pr['number']))
                self.output_text_ctrl.AppendText(_("🔗 URL: {}\n").format(updated_pr['html_url']))

            edit_dlg.Destroy()

        except requests.exceptions.RequestException as e:
            self.output_text_ctrl.AppendText(_("❌ Errore durante la modifica: {}\n").format(e))

    def handle_delete_pr(self, command_name_key, command_details):
        """Gestisce la chiusura di una Pull Request"""
        if not self.github_owner or not self.github_repo or not self.github_token:
            self.output_text_ctrl.AppendText(_("ERRORE: Repository GitHub e token non configurati.\n"))
            return

        headers = {"Authorization": f"Bearer {self.github_token}", "Accept": "application/vnd.github.v3+json"}
        
        # Carica PR aperte
        prs_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/pulls"
        params = {"state": "open", "per_page": 50}

        try:
            response = requests.get(prs_url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            prs_data = response.json()
            
            if not prs_data:
                self.output_text_ctrl.AppendText(_("Nessuna Pull Request aperta trovata da chiudere.\n"))
                return

            # Selezione PR da chiudere
            pr_choices = [f"#{pr['number']}: {pr['title']} ({pr['head']['ref']} → {pr['base']['ref']})" for pr in prs_data]
            pr_map = {choice: pr for choice, pr in zip(pr_choices, prs_data)}

            select_dlg = wx.SingleChoiceDialog(self, 
                                             _("Seleziona la PR da chiudere:"),
                                             _("Chiudi Pull Request"),
                                             pr_choices,
                                             wx.CHOICEDLG_STYLE)

            if select_dlg.ShowModal() != wx.ID_OK:
                self.output_text_ctrl.AppendText(_("Chiusura PR annullata.\n"))
                select_dlg.Destroy()
                return

            selected_pr = pr_map[select_dlg.GetStringSelection()]
            select_dlg.Destroy()

            # Conferma chiusura
            confirm_msg = _("Sei sicuro di voler chiudere la Pull Request:\n\n#{}: {}\n\nBranch: {} → {}\n\nQuesta azione può essere annullata riaprendo la PR su GitHub.").format(
                selected_pr['number'], selected_pr['title'], selected_pr['head']['ref'], selected_pr['base']['ref']
            )
            
            confirm_dlg = wx.MessageDialog(self, confirm_msg, _("Conferma Chiusura PR"), 
                                         wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)

            if confirm_dlg.ShowModal() != wx.ID_YES:
                self.output_text_ctrl.AppendText(_("Chiusura PR annullata.\n"))
                confirm_dlg.Destroy()
                return
            
            confirm_dlg.Destroy()

            # Chiudi PR via API
            close_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/pulls/{selected_pr['number']}"
            close_payload = {"state": "closed"}

            self.output_text_ctrl.AppendText(_("🔒 Chiusura PR #{}...\n").format(selected_pr['number']))
            wx.Yield()

            close_response = requests.patch(close_url, headers=headers, json=close_payload, timeout=15)
            close_response.raise_for_status()
            
            self.output_text_ctrl.AppendText(_("✅ PR #{} chiusa con successo!\n").format(selected_pr['number']))

        except requests.exceptions.RequestException as e:
            self.output_text_ctrl.AppendText(_("❌ Errore durante la chiusura: {}\n").format(e))

    def get_repository_labels(self):
        """Recupera le labels disponibili nel repository"""
        if not self.github_owner or not self.github_repo or not self.github_token:
            return []
        
        headers = {"Authorization": f"Bearer {self.github_token}", "Accept": "application/vnd.github.v3+json"}
        labels_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/labels"
        
        try:
            response = requests.get(labels_url, headers=headers, timeout=10)
            response.raise_for_status()
            labels_data = response.json()
            return [label['name'] for label in labels_data]
        except:
            return ["bug", "enhancement", "documentation", "question", "help wanted", "good first issue"]

    def get_repository_collaborators(self):
        """Recupera i collaboratori del repository"""
        if not self.github_owner or not self.github_repo or not self.github_token:
            return []
        
        headers = {"Authorization": f"Bearer {self.github_token}", "Accept": "application/vnd.github.v3+json"}
        collaborators_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/collaborators"
        
        try:
            response = requests.get(collaborators_url, headers=headers, timeout=10)
            response.raise_for_status()
            collaborators_data = response.json()
            return [collab['login'] for collab in collaborators_data]
        except:
            return []

    def get_repository_branches(self):
        """Recupera i branch del repository"""
        if not self.github_owner or not self.github_repo:
            return []
        
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
        
        branches_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/branches"
        
        try:
            response = requests.get(branches_url, headers=headers, timeout=10)
            response.raise_for_status()
            branches_data = response.json()
            return [branch['name'] for branch in branches_data]
        except:
            return ["main", "master", "develop"]

    def get_current_git_branch(self):
        """Recupera il branch corrente dal repository locale"""
        try:
            repo_path = self.repo_path_ctrl.GetValue()
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass
        return None

    def GetLocalBranches(self, repo_path):
            """Recupera la lista dei branch locali disponibili."""
            try:
                process_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                proc = subprocess.run(
                    ["git", "branch"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    check=True,
                    encoding='utf-8',
                    errors='replace',
                    creationflags=process_flags
                )
                # Parsing output: ogni riga è "  branch_name" o "* current_branch"
                branches = []
                for line in proc.stdout.strip().splitlines():
                    branch_name = line.strip().lstrip('* ').strip()
                    if branch_name and not branch_name.startswith('('):  # Esclude "(HEAD detached at ...)"
                        branches.append(branch_name)
                return branches
            except (subprocess.CalledProcessError, FileNotFoundError, Exception) as e:
                print(f"DEBUG: Errore nel recuperare i branch locali: {e}")
                return []
                
    # Aggiungi queste parti al metodo ExecuteGithubCommand

    def handle_create_issue(self, command_name_key, command_details):
        """Gestisce la creazione di una nuova issue"""
        if not self.github_owner or not self.github_repo:
            self.output_text_ctrl.AppendText(_("ERRORE: Repository GitHub non configurato.\n"))
            return
        
        if not self.github_token:
            self.output_text_ctrl.AppendText(_("ERRORE: Token GitHub necessario per creare issue.\n"))
            return
        
        # Recupera labels e assignees disponibili
        self.output_text_ctrl.AppendText(_("Recupero informazioni repository...\n"))
        wx.Yield()
        
        labels_list = self.get_repository_labels()
        assignees_list = self.get_repository_collaborators()
        
        # Mostra dialog per creare issue
        dlg = CreateIssueDialog(self, _("Crea Nuova Issue"), labels_list, assignees_list)
        
        if dlg.ShowModal() == wx.ID_OK:
            values = dlg.GetValues()
            
            if not values["title"].strip():
                self.output_text_ctrl.AppendText(_("ERRORE: Il titolo dell'issue è obbligatorio.\n"))
                dlg.Destroy()
                return
            
            # Prepara payload per API
            payload = {
                "title": values["title"],
                "body": values["body"],
                "labels": values["labels"],
                "assignees": values["assignees"]
            }
            
            # Crea issue via API
            headers = {"Authorization": f"Bearer {self.github_token}", "Accept": "application/vnd.github.v3+json"}
            issues_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/issues"
            
            self.output_text_ctrl.AppendText(_("🚀 Creazione issue '{}' in corso...\n").format(values["title"]))
            wx.Yield()
            
            try:
                response = requests.post(issues_url, headers=headers, json=payload, timeout=15)
                response.raise_for_status()
                
                issue_data = response.json()
                issue_number = issue_data["number"]
                issue_url = issue_data["html_url"]
                
                self.output_text_ctrl.AppendText(_("✅ Issue #{} creata con successo!\n").format(issue_number))
                self.output_text_ctrl.AppendText(_("🔗 URL: {}\n").format(issue_url))
                
                # Opzione per aprire nel browser
                open_browser_msg = _("Vuoi aprire l'issue nel browser?")
                open_dlg = wx.MessageDialog(self, open_browser_msg, _("Apri Issue"), wx.YES_NO | wx.ICON_QUESTION)
                if open_dlg.ShowModal() == wx.ID_YES:
                    import webbrowser
                    webbrowser.open(issue_url)
                open_dlg.Destroy()
                
            except requests.exceptions.RequestException as e:
                self.output_text_ctrl.AppendText(_("❌ Errore durante la creazione dell'issue: {}\n").format(e))
                if hasattr(e, 'response') and e.response is not None:
                    self.output_text_ctrl.AppendText(_("Dettagli errore: {}\n").format(e.response.text[:300]))
        else:
            self.output_text_ctrl.AppendText(_("Creazione issue annullata.\n"))
        
        dlg.Destroy()

    def handle_create_pull_request(self, command_name_key, command_details):
        """Gestisce la creazione di una nuova pull request"""
        if not self.github_owner or not self.github_repo:
            self.output_text_ctrl.AppendText(_("ERRORE: Repository GitHub non configurato.\n"))
            return
        
        if not self.github_token:
            self.output_text_ctrl.AppendText(_("ERRORE: Token GitHub necessario per creare PR.\n"))
            return
        
        # Recupera branch disponibili e branch corrente
        self.output_text_ctrl.AppendText(_("Recupero informazioni branch...\n"))
        wx.Yield()
        
        branches_list = self.get_repository_branches()
        current_branch = self.get_current_git_branch()
        
        if not branches_list:
            self.output_text_ctrl.AppendText(_("ERRORE: Impossibile recuperare i branch del repository.\n"))
            return
        
        # Mostra dialog per creare PR
        dlg = CreatePullRequestDialog(self, _("Crea Nuova Pull Request"), branches_list, current_branch)
        
        if dlg.ShowModal() == wx.ID_OK:
            values = dlg.GetValues()
            
            if not values["title"].strip():
                self.output_text_ctrl.AppendText(_("ERRORE: Il titolo della PR è obbligatorio.\n"))
                dlg.Destroy()
                return
            
            if not values["head"] or not values["base"]:
                self.output_text_ctrl.AppendText(_("ERRORE: Branch di origine e destinazione sono obbligatori.\n"))
                dlg.Destroy()
                return
            
            if values["head"] == values["base"]:
                self.output_text_ctrl.AppendText(_("ERRORE: Branch di origine e destinazione non possono essere uguali.\n"))
                dlg.Destroy()
                return
            
            # Prepara payload per API
            payload = {
                "title": values["title"],
                "body": values["body"],
                "head": values["head"],
                "base": values["base"],
                "draft": values["draft"]
            }
            
            # Crea PR via API
            headers = {"Authorization": f"Bearer {self.github_token}", "Accept": "application/vnd.github.v3+json"}
            pr_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/pulls"
            
            self.output_text_ctrl.AppendText(_("🚀 Creazione PR '{}' da '{}' verso '{}'...\n").format(
                values["title"], values["head"], values["base"]))
            wx.Yield()
            
            try:
                response = requests.post(pr_url, headers=headers, json=payload, timeout=15)
                response.raise_for_status()
                
                pr_data = response.json()
                pr_number = pr_data["number"]
                pr_html_url = pr_data["html_url"]
                
                self.output_text_ctrl.AppendText(_("✅ Pull Request #{} creata con successo!\n").format(pr_number))
                self.output_text_ctrl.AppendText(_("🔗 URL: {}\n").format(pr_html_url))
                
                # Se auto-merge è richiesto e la PR non è draft
                if values["auto_merge"] and not values["draft"]:
                    self.output_text_ctrl.AppendText(_("🔄 Tentativo di abilitare auto-merge...\n"))
                    # Nota: l'auto-merge richiede API specifiche e configurazione repository
                
                # Opzione per aprire nel browser
                open_browser_msg = _("Vuoi aprire la PR nel browser?")
                open_dlg = wx.MessageDialog(self, open_browser_msg, _("Apri PR"), wx.YES_NO | wx.ICON_QUESTION)
                if open_dlg.ShowModal() == wx.ID_YES:
                    import webbrowser
                    webbrowser.open(pr_html_url)
                open_dlg.Destroy()
                
            except requests.exceptions.RequestException as e:
                self.output_text_ctrl.AppendText(_("❌ Errore durante la creazione della PR: {}\n").format(e))
                if hasattr(e, 'response') and e.response is not None:
                    error_details = e.response.text[:300]
                    self.output_text_ctrl.AppendText(_("Dettagli errore: {}\n").format(error_details))
                    
                    # Gestione errori specifici
                    if "No commits between" in error_details:
                        self.output_text_ctrl.AppendText(_("💡 Suggerimento: Assicurati che ci siano commit nel branch '{}' che non sono in '{}'.\n").format(values["head"], values["base"]))
                    elif "A pull request already exists" in error_details:
                        self.output_text_ctrl.AppendText(_("💡 Suggerimento: Una PR tra questi branch potrebbe già esistere.\n"))
        else:
            self.output_text_ctrl.AppendText(_("Creazione PR annullata.\n"))
        
        dlg.Destroy()


    def start_monitoring_run(self, run_id, owner, repo):
        """Avvia il monitoraggio periodico di un workflow run."""
        print(f"DEBUG_MONITOR: Avvio monitoraggio per run_id: {run_id}")
        
        # Interrompi qualsiasi monitoraggio precedente
        self.stop_monitoring_run()
        
        # Imposta i parametri del monitoraggio
        self.monitoring_run_id = run_id
        self.monitoring_owner = owner
        self.monitoring_repo = repo
        self.monitoring_start_time = time.time()
        self.monitoring_max_duration = 30 * 60  # 30 minuti
        self.monitoring_poll_count = 0
        
        # Avvia il timer
        self.monitoring_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_monitoring_timer, self.monitoring_timer)
        
        # Polling ogni 10 secondi
        polling_interval = 10000  # milliseconds
        self.monitoring_timer.Start(polling_interval)
        
        print(f"DEBUG_MONITOR: Timer avviato con successo per run_id {run_id}. Intervallo: {polling_interval}ms")
        
        self.output_text_ctrl.AppendText(
            f"⏱️ Monitoraggio avviato per workflow run ID {run_id}.\n"
            f"Polling ogni 10 secondi. Durata massima: 30 minuti.\n"
        )


    def stop_monitoring_run(self):
        """Interrompe il monitoraggio corrente."""
        if hasattr(self, 'monitoring_timer') and self.monitoring_timer and self.monitoring_timer.IsRunning():
            print("DEBUG_MONITOR: Interruzione timer esistente")
            self.monitoring_timer.Stop()
            self.monitoring_timer.Destroy()
            self.monitoring_timer = None
        
        # Reset delle variabili di monitoraggio
        self.monitoring_run_id = None
        self.monitoring_owner = None
        self.monitoring_repo = None
        self.monitoring_start_time = None
        self.monitoring_poll_count = 0
    def on_monitoring_timer(self, event):
        """Callback del timer per il monitoraggio del workflow run."""
        try:
            # 1) Incremento del contatore di poll e calcolo del tempo trascorso
            self.monitoring_poll_count += 1
            elapsed_time = (time.time() - self.monitoring_start_time) if self.monitoring_start_time else 0

            # 2) Controllo timeout assoluto del monitoraggio
            if elapsed_time > self.monitoring_max_duration:
                self.output_text_ctrl.AppendText(
                    f"⏰ Timeout monitoraggio per run ID {self.monitoring_run_id} "
                    f"(durata: {elapsed_time/60:.1f} minuti)\n"
                )
                self.stop_monitoring_run()
                return

            # 3) Se mancano dati essenziali (run_id, owner o repo), fermo tutto
            if not self.monitoring_run_id or not self.monitoring_owner or not self.monitoring_repo:
                print("DEBUG_MONITOR: Parametri monitoraggio mancanti, interruzione")
                self.stop_monitoring_run()
                return

            # 4) Chiamata API a GitHub per ottenere lo stato corrente del run
            headers = {
                "Accept": "application/vnd.github.v3+json",
                "X-GitHub-Api-Version": "2022-11-28"
            }
            if self.github_token:
                headers["Authorization"] = f"Bearer {self.github_token}"
            
            api_url = (
                f"https://api.github.com/repos/"
                f"{self.monitoring_owner}/{self.monitoring_repo}/actions/runs/"
                f"{self.monitoring_run_id}"
            )
            
            print(f"DEBUG_MONITOR: Poll #{self.monitoring_poll_count} - Chiamata API: {api_url}")
            
            response = requests.get(api_url, headers=headers, timeout=10)
            response.raise_for_status()
            run_data = response.json()
            current_status = run_data.get("status", "unknown").lower()
            current_conclusion = run_data.get("conclusion")

            print(f"DEBUG_MONITOR: Status: {current_status}, Conclusion: {current_conclusion}")

            # 5) Stati che indicano che il workflow è ancora in progress
            in_progress_states = [
                "queued", "in_progress", "waiting", "requested", "pending", "action_required"
            ]
            
            if current_status in in_progress_states:
                print(f"DEBUG_MONITOR: Workflow ancora in corso ({current_status})")
                # Emetti beep solo se abilitato
                if getattr(self, "github_monitoring_beep", True):
                    if os.name == "nt":
                        try:
                            import winsound
                            winsound.Beep(800, 150)
                        except ImportError:
                            wx.Bell()
                    else:
                        wx.Bell()
                return  # esco e aspetto il prossimo tick del timer

            # 6) Il workflow NON è più "in progress" → è terminato o cancellato
            print(f"DEBUG_MONITOR: Workflow terminato! Status: {current_status}, Conclusion: {current_conclusion}")
            
            # Recupero dati locali prima di azzerare lo stato
            run_id_local = self.monitoring_run_id
            owner_local = self.monitoring_owner
            repo_local = self.monitoring_repo
            workflow_name_local = getattr(self, "monitoring_workflow_name", "(anonimo)")
            duration_local = elapsed_time

            # 7) Ferma subito il timer e pulisci lo stato interno
            self.stop_monitoring_run()

            # 8) Preparo il testo da mostrare in base alla conclusione
            if current_conclusion == "success":
                icon = "✅"
                result = "completato con SUCCESSO"
            elif current_conclusion == "failure":
                icon = "❌"
                result = "FALLITO"
            elif current_conclusion == "cancelled":
                icon = "🚫"
                result = "CANCELLATO"
            elif current_conclusion == "skipped":
                icon = "⏭️"
                result = "SALTATO"
            elif current_conclusion == "timed_out":
                icon = "⏰"
                result = "SCADUTO (timeout)"
            else:
                icon = "🏁"
                result = f"terminato (conclusione: {current_conclusion or 'N/D'})"

            message = (
                f"{icon} WORKFLOW COMPLETATO!\n\n"
                f"Nome: {workflow_name_local}\n"
                f"Run ID: {run_id_local}\n"
                f"Repository: {owner_local}/{repo_local}\n"
                f"Risultato: {result}\n"
                f"Durata monitoraggio: {duration_local/60:.1f} minuti\n\n"
                "Usa i comandi per visualizzare log o scaricare artefatti."
            )

            # 9) Apro un MessageDialog di notifica
            dialog_title = f"Workflow {result.upper()}"
            icon_style = wx.ICON_INFORMATION if current_conclusion == "success" else wx.ICON_WARNING
            
            dlg = wx.MessageDialog(
                parent=self,
                message=message,
                caption=dialog_title,
                style=wx.OK | icon_style
            )
            dlg.ShowModal()
            dlg.Destroy()

            # 10) Loggo anche nel TextCtrl
            self.output_text_ctrl.AppendText(
                f"\n{icon} WORKFLOW COMPLETATO!\n"
                f"Nome: {workflow_name_local}\n"
                f"Run ID: {run_id_local}\n"
                f"Repository: {owner_local}/{repo_local}\n"
                f"Risultato: {result}\n"
                f"Durata monitoraggio: {duration_local/60:.1f} minuti\n"
                "Usa i comandi per visualizzare log o scaricare artefatti.\n\n"
            )

        except requests.exceptions.HTTPError as http_err:
            # Gestione specifica per errori HTTP (es. 404 quando la run viene cancellata)
            if http_err.response.status_code == 404:
                print(f"DEBUG_MONITOR: Run ID {self.monitoring_run_id} non trovata (404) - probabilmente cancellata")
                
                # Recupero dati prima di fermare il monitoraggio
                run_id_local = self.monitoring_run_id
                owner_local = self.monitoring_owner
                repo_local = self.monitoring_repo
                workflow_name_local = getattr(self, "monitoring_workflow_name", "(anonimo)")
                duration_local = (time.time() - self.monitoring_start_time) if self.monitoring_start_time else 0
                
                # Ferma il monitoraggio
                self.stop_monitoring_run()
                
                # Notifica della cancellazione
                cancel_message = (
                    f"🚫 WORKFLOW CANCELLATO/RIMOSSO!\n\n"
                    f"Nome: {workflow_name_local}\n"
                    f"Run ID: {run_id_local}\n"
                    f"Repository: {owner_local}/{repo_local}\n"
                    f"Il workflow è stato cancellato o rimosso da GitHub.\n"
                    f"Durata monitoraggio: {duration_local/60:.1f} minuti\n"
                )
                
                # Mostra dialog di notifica
                dlg = wx.MessageDialog(
                    parent=self,
                    message=cancel_message,
                    caption="Workflow Cancellato/Rimosso",
                    style=wx.OK | wx.ICON_WARNING
                )
                dlg.ShowModal()
                dlg.Destroy()
                
                # Log nel TextCtrl
                self.output_text_ctrl.AppendText(f"\n{cancel_message}\n")
                
            else:
                print(f"DEBUG_MONITOR: Errore HTTP {http_err.response.status_code} durante monitoraggio: {http_err}")
                self.output_text_ctrl.AppendText(f"❌ Errore HTTP durante monitoraggio: {http_err}\n")
                # Non interrompiamo il monitoraggio per altri errori HTTP, potrebbe essere temporaneo
                
        except requests.exceptions.RequestException as req_err:
            print(f"DEBUG_MONITOR: Errore di rete durante monitoraggio: {req_err}")
            # Non interrompiamo il monitoraggio per errori temporanei di rete
            self.output_text_ctrl.AppendText(f"⚠️ Errore temporaneo di rete durante monitoraggio: {req_err}\n")
            
        except Exception as e:
            print(f"DEBUG_MONITOR: Errore imprevisto durante monitoraggio: {e}")
            self.output_text_ctrl.AppendText(f"❌ Errore imprevisto durante monitoraggio: {e}\n")
            self.stop_monitoring_run()
    def convert_utc_to_local_timestamp_match(self, ts_match):
        utc_str = ts_match.group(1)
        print(f"DEBUG_TIMESTAMP: Trovato timestamp potenziale da convertire: '{utc_str}'")
        try:
            # Gestisce diversi formati di timestamp UTC
            if utc_str.endswith('Z'):
                # Sostituisci 'Z' con '+00:00' per datetime.fromisoformat()
                utc_dt = datetime.fromisoformat(utc_str[:-1] + '+00:00')
            elif '+00:00' in utc_str:
                utc_dt = datetime.fromisoformat(utc_str)
            elif utc_str.endswith('+0000'):
                # Formato senza due punti nel fuso orario
                utc_dt = datetime.fromisoformat(utc_str[:-5] + '+00:00')
            else:
                # Assume UTC se non c'è indicazione di fuso orario
                utc_dt = datetime.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
                
            print(f"DEBUG_TIMESTAMP: Parsed UTC datetime: {utc_dt}")
            
            # Converte al fuso orario locale del sistema
            local_dt = utc_dt.astimezone()
            print(f"DEBUG_TIMESTAMP: Converted to local datetime: {local_dt}")
            
            formatted_local_dt = local_dt.strftime('%Y-%m-%d %H:%M:%S (Locale)')
            print(f"DEBUG_TIMESTAMP: Formattato localmente come: '{formatted_local_dt}'")
            return formatted_local_dt
            
        except ValueError as e:
            print(f"DEBUG_TIMESTAMP: Errore parsing/conversione timestamp: {e} per '{utc_str}'")
            return ts_match.group(0)
        except Exception as ex:
            print(f"DEBUG_TIMESTAMP: Errore generico in conversione: {ex} per '{utc_str}'")
            return ts_match.group(0)
            # --- Metodi per la gestione della configurazione sicura e delle opzioni ---
    def _get_app_config_dir(self):
        sp = wx.StandardPaths.Get()
        config_dir = sp.GetUserConfigDir()
        app_config_path = os.path.join(config_dir, APP_CONFIG_DIR_NAME)
        if not os.path.exists(app_config_path):
            try:
                os.makedirs(app_config_path)
            except OSError as e:
                print(f"DEBUG: Errore creazione directory config app: {e}")
                app_config_path = os.path.join(script_dir, "." + APP_CONFIG_DIR_NAME.lower())
                if not os.path.exists(app_config_path):
                    try: os.makedirs(app_config_path)
                    except: pass
        return app_config_path

    def _get_or_create_user_uuid(self):
        app_conf_dir = self._get_app_config_dir()
        uuid_file_path = os.path.join(app_conf_dir, USER_ID_FILE_NAME)
        try:
            if os.path.exists(uuid_file_path):
                with open(uuid_file_path, 'r') as f:
                    user_uuid_str = f.read().strip()
                    return uuid.UUID(user_uuid_str)
            else:
                new_uuid = uuid.uuid4()
                with open(uuid_file_path, 'w') as f:
                    f.write(str(new_uuid))
                return new_uuid
        except Exception as e:
            print(f"DEBUG: Errore gestione UUID utente: {e}. Generazione di un UUID temporaneo.")
            return uuid.uuid4()

    def _get_secure_config_path(self):
        return os.path.join(self._get_app_config_dir(), SECURE_CONFIG_FILE_NAME)

    def _derive_key(self, password: str, salt: bytes) -> bytes:
        if not isinstance(password, bytes):
            password = password.encode('utf-8')
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=PBKDF2_ITERATIONS,
            backend=default_backend()
        )
        raw_key = kdf.derive(password)
        fernet_key = base64.urlsafe_b64encode(raw_key)
        return fernet_key

    def _encrypt_data(self, data: bytes, password: str) -> tuple[bytes | None, bytes | None, str | None]:
        try:
            salt = os.urandom(SALT_SIZE)
            derived_fernet_key = self._derive_key(password, salt)
            f = Fernet(derived_fernet_key)
            compressed_data = gzip.compress(data)
            encrypted_data = f.encrypt(compressed_data)
            return salt, encrypted_data, None
        except Exception as e:
            error_message = f"{type(e).__name__}: {e}"
            print(f"DEBUG: Errore imprevisto in _encrypt_data: {error_message}")
            return None, None, error_message

    def _decrypt_data(self, encrypted_data: bytes, salt: bytes, password: str) -> tuple[bytes | None, str | None]:
        try:
            derived_fernet_key = self._derive_key(password, salt)
            f = Fernet(derived_fernet_key)
            decrypted_compressed_data = f.decrypt(encrypted_data)
            original_data = gzip.decompress(decrypted_compressed_data)
            return original_data, None
        except InvalidToken:
            error_message = _("Password Master errata o dati corrotti (InvalidToken).")
            print(f"DEBUG: {error_message}")
            return None, error_message
        except (gzip.BadGzipFile, Exception) as e:
            error_message = f"{type(e).__name__}: {e}"
            print(f"DEBUG: Errore di decrittografia o decompressione: {error_message}")
            return None, error_message

    def _save_app_settings(self):
        """Salva le opzioni non sensibili in settings.json."""
        settings_data = {
            "ask_pass_on_startup": self.github_ask_pass_on_startup,
            "strip_log_timestamps": self.github_strip_log_timestamps,
            "monitoring_beep": self.github_monitoring_beep
        }
        try:
            with open(self.app_settings_path, 'w') as f:
                json.dump(settings_data, f, indent=4)
            print(f"DEBUG: Opzioni app salvate in {self.app_settings_path}")
        except IOError as e:
            print(f"DEBUG: Errore nel salvare settings.json: {e}")
            self.output_text_ctrl.AppendText(_("Errore nel salvare le opzioni dell'applicazione: {}\n").format(e))

    def _load_app_settings(self):
        """Carica le opzioni non sensibili da settings.json all'avvio."""
        if os.path.exists(self.app_settings_path):
            try:
                with open(self.app_settings_path, 'r') as f:
                    settings_data = json.load(f)
                    self.github_ask_pass_on_startup = settings_data.get("ask_pass_on_startup", True)
                    self.github_strip_log_timestamps = settings_data.get("strip_log_timestamps", False)
                    self.github_monitoring_beep = settings_data.get("monitoring_beep", True)  # ← 
                    print(f"DEBUG: Opzioni caricate da settings.json: ask_pass={self.github_ask_pass_on_startup}, strip_ts={self.github_strip_log_timestamps}")
            except (IOError, json.JSONDecodeError) as e:
                print(f"DEBUG: Errore nel caricare settings.json: {e}. Uso i default.")
                self.github_ask_pass_on_startup = True
                self.github_strip_log_timestamps = False
                self.github_monitoring_beep = True
        else:
            print("DEBUG: settings.json non trovato. Uso i default per le opzioni.")
            self.github_ask_pass_on_startup = True
            self.github_strip_log_timestamps = False
            self.github_monitoring_beep = True

        self.output_text_ctrl.AppendText(_("Opzione 'Richiedi password all'avvio': {}.\n").format(
            _("Abilitata") if self.github_ask_pass_on_startup else _("Disabilitata")
        ))    
    def _save_github_config(self, owner: str, repo: str, token: str, password: str, # password is from dialog
                                ask_pass_startup: bool, strip_timestamps: bool, monitoring_beep: bool): # ask_pass_startup is from dialog
            """Salva la configurazione GitHub. La password è usata per crittografare/ri-crittografare."""
            
            password_master_for_encryption: str
            if ask_pass_startup:
                if not password: # Password from dialog is empty
                    wx.MessageBox(
                        _("Se 'Richiedi password master all'avvio' è selezionato, la Password Master è necessaria per salvare/aggiornare il token o i dettagli GitHub crittografati."),
                        _("Password Mancante"), wx.OK | wx.ICON_ERROR, self
                    )
                    return False 
                password_master_for_encryption = password
            else: # ask_pass_startup is False, user can provide an empty password to "encrypt" with it
                password_master_for_encryption = password # This can be ""

            config_data = {
                "owner": owner,
                "repo": repo,
                "token": token,
                # Le opzioni seguenti sono state spostate in settings.json ma le includiamo qui
                # per compatibilità con file .agd più vecchi durante la decrittografia.
                # Non verranno più lette attivamente da qui se settings.json esiste.
                "ask_pass_on_startup": ask_pass_startup, # Kept for older files, but primarily driven by settings.json now
                "strip_log_timestamps": strip_timestamps # Kept for older files
            }
            json_data = json.dumps(config_data).encode('utf-8')

            salt, encrypted_data, error_msg_encrypt = self._encrypt_data(json_data, password_master_for_encryption)

            if error_msg_encrypt is not None:
                self.output_text_ctrl.AppendText(_("Fallimento crittografia: {}\n").format(error_msg_encrypt))
                wx.MessageBox(
                    _("Errore durante la crittografia dei dati: {}\nConfigurazione non salvata.").format(error_msg_encrypt),
                    _("Errore Crittografia"), wx.OK | wx.ICON_ERROR, self
                )
                return False

            if salt is None or encrypted_data is None:
                self.output_text_ctrl.AppendText(
                    _("Errore interno sconosciuto durante la crittografia (salt o dati None).\n")
                )
                wx.MessageBox(
                    _("Errore interno sconosciuto durante la crittografia. Configurazione non salvata."),
                    _("Errore Crittografia"), wx.OK | wx.ICON_ERROR, self
                )
                return False

            magic_part_uuid = self.user_uuid.bytes[:4]

            try:
                with open(self.secure_config_path, 'wb') as f:
                    f.write(CONFIG_MAGIC_NUMBER_PREFIX)
                    f.write(magic_part_uuid)
                    f.write(struct.pack('<I', CONFIG_FORMAT_VERSION))
                    f.write(struct.pack('<I', len(salt)))
                    f.write(salt)
                    f.write(struct.pack('<I', len(encrypted_data)))
                    f.write(encrypted_data)

                self.output_text_ctrl.AppendText(_("Configurazione GitHub salvata e crittografata con successo.\n"))
                self.github_owner = owner
                self.github_repo = repo
                self.github_token = token
                self.github_monitoring_beep = monitoring_beep
                # self.github_ask_pass_on_startup e self.github_strip_log_timestamps sono già stati aggiornati
                # nell'istanza e salvati in settings.json prima di chiamare questa funzione.
                # Li abbiamo inclusi in config_data per la (de)crittografia ma non è necessario riassegnarli qui.
                return True
            except Exception as e:
                error_detail = f"{type(e).__name__}: {e}"
                self.output_text_ctrl.AppendText(
                    _("Errore durante il salvataggio del file di configurazione crittografato: {}\n").format(error_detail)
                )
                wx.MessageBox(
                    _("Errore durante il salvataggio della configurazione nel file: {}").format(error_detail),
                    _("Errore Salvataggio File"), wx.OK | wx.ICON_ERROR, self
                )
                return False
    def _prompt_and_load_github_config(self, called_from_startup=False):
        if not os.path.exists(self.secure_config_path):
            if not called_from_startup:
                self.output_text_ctrl.AppendText(_("File di configurazione GitHub sicuro non trovato. Configurare prima.\n"))
                wx.MessageBox(_("File di configurazione GitHub non trovato. Utilizza '{}'.").format(CMD_GITHUB_CONFIGURE), _("Configurazione Mancante"), wx.OK | wx.ICON_INFORMATION, self)
            return False

        password_dialog = wx.PasswordEntryDialog(self, _("Inserisci la Password Master per sbloccare i dati GitHub (token, owner, repo):"), _("Password Master Richiesta"))
        if password_dialog.ShowModal() == wx.ID_OK:
            password = password_dialog.GetValue()
            if not password:
                self.output_text_ctrl.AppendText(_("Password non inserita. Impossibile caricare i dati GitHub.\n"))
                password_dialog.Destroy()
                return False

            try:
                with open(self.secure_config_path, 'rb') as f:
                    magic_prefix = f.read(len(CONFIG_MAGIC_NUMBER_PREFIX))
                    magic_uuid_part = f.read(4)
                    expected_magic_uuid_part = self.user_uuid.bytes[:4]

                    if magic_prefix != CONFIG_MAGIC_NUMBER_PREFIX or magic_uuid_part != expected_magic_uuid_part:
                        msg_err = _("File di configurazione dati sensibili non valido o corrotto (magic number/UUID errato).")
                        self.output_text_ctrl.AppendText(msg_err + "\n")
                        wx.MessageBox(msg_err, _("Errore Caricamento"), wx.OK | wx.ICON_ERROR, self)
                        password_dialog.Destroy(); return False

                    version = struct.unpack('<I', f.read(4))[0]
                    if version > CONFIG_FORMAT_VERSION:
                        msg_err = _("Versione del file di configurazione dati sensibili (v{}) non supportata (max v{}).\nSi prega di aggiornare l'applicazione o eliminare il file di configurazione.").format(version, CONFIG_FORMAT_VERSION)
                        self.output_text_ctrl.AppendText(msg_err + "\n")
                        wx.MessageBox(msg_err, _("Errore Caricamento"), wx.OK | wx.ICON_ERROR, self)
                        password_dialog.Destroy(); return False

                    salt_len = struct.unpack('<I', f.read(4))[0]
                    salt = f.read(salt_len)
                    encrypted_data_len = struct.unpack('<I', f.read(4))[0]
                    encrypted_data = f.read(encrypted_data_len)

                decrypted_json_data, error_msg_decrypt = self._decrypt_data(encrypted_data, salt, password)
                if error_msg_decrypt is not None:
                    self.output_text_ctrl.AppendText(_("Errore durante la decrittografia dei dati sensibili: {}\n").format(error_msg_decrypt))
                    wx.MessageBox(_("Errore durante la decrittografia: {}").format(error_msg_decrypt),
                                  _("Errore Decrittografia"), wx.OK | wx.ICON_ERROR, self)
                    password_dialog.Destroy(); return False
                elif decrypted_json_data:
                    config_data = json.loads(decrypted_json_data.decode('utf-8'))
                    self.github_owner = config_data.get("owner", "")
                    self.github_repo = config_data.get("repo", "")
                    self.github_token = config_data.get("token", "")
                    # Le opzioni non sensibili sono già caricate da _load_app_settings.
                    # Se il file .agd è vecchio e le contiene, le ignoriamo qui perché settings.json ha la precedenza.
                    # self.github_ask_pass_on_startup = config_data.get("ask_pass_on_startup", self.github_ask_pass_on_startup) # Non sovrascrivere da .agd
                    # self.github_strip_log_timestamps = config_data.get("strip_log_timestamps", self.github_strip_log_timestamps) # Non sovrascrivere da .agd

                    self.output_text_ctrl.AppendText(_("Dati sensibili GitHub (owner, repo, token) caricati con successo.\n"))
                    if self.github_token: self.output_text_ctrl.AppendText(_("Token PAT GitHub caricato.\n"))
                    else: self.output_text_ctrl.AppendText(_("Token PAT GitHub non presente nella configurazione caricata.\n"))
                    password_dialog.Destroy(); return True
                else:
                    msg_err = _("Errore sconosciuto durante la decrittografia dei dati sensibili (possibile password errata).")
                    self.output_text_ctrl.AppendText(msg_err + "\n")
                    wx.MessageBox(msg_err, _("Errore Decrittografia"), wx.OK | wx.ICON_ERROR, self)
                    password_dialog.Destroy(); return False
            except FileNotFoundError:
                   self.output_text_ctrl.AppendText(_("File di configurazione GitHub sicuro non trovato.\n"))
                   password_dialog.Destroy(); return False
            except Exception as e:
                error_detail = f"{type(e).__name__}: {e}"
                self.output_text_ctrl.AppendText(_("Errore durante il caricamento dei dati GitHub: {}\n").format(error_detail))
                wx.MessageBox(_("Errore imprevisto durante il caricamento: {}").format(error_detail), _("Errore Caricamento"), wx.OK | wx.ICON_ERROR, self)
                password_dialog.Destroy(); return False
        else:
            self.output_text_ctrl.AppendText(_("Caricamento dati GitHub annullato (password non inserita).\n"))
            password_dialog.Destroy(); return False
        return False

    def _ensure_github_config_loaded(self):
        if self.github_token:
            return True

        if not self.github_ask_pass_on_startup:
            if not os.path.exists(self.secure_config_path):
                self.output_text_ctrl.AppendText(
                    _("Errore: file di configurazione GitHub non trovato. Usa '{}'.\n").format(CMD_GITHUB_CONFIGURE)
                )
                return False

            try:
                with open(self.secure_config_path, 'rb') as f:
                    magic_prefix = f.read(len(CONFIG_MAGIC_NUMBER_PREFIX))
                    magic_uuid_part = f.read(4)
                    expected_magic_uuid_part = self.user_uuid.bytes[:4]
                    if magic_prefix != CONFIG_MAGIC_NUMBER_PREFIX or magic_uuid_part != expected_magic_uuid_part:
                        raise ValueError("Magic number o UUID non valido")
                    version = struct.unpack('<I', f.read(4))[0]
                    if version > CONFIG_FORMAT_VERSION:
                        raise ValueError(f"Versione file ({version}) > {CONFIG_FORMAT_VERSION}")

                    salt_len = struct.unpack('<I', f.read(4))[0]
                    salt = f.read(salt_len)
                    encrypted_data_len = struct.unpack('<I', f.read(4))[0]
                    encrypted_data = f.read(encrypted_data_len)

                decrypted_json_data, error_msg_decrypt = self._decrypt_data(encrypted_data, salt, "") # Tenta con password vuota
                if error_msg_decrypt is None and decrypted_json_data:
                    config_data = json.loads(decrypted_json_data.decode('utf-8'))
                    self.github_owner = config_data.get("owner", "")
                    self.github_repo = config_data.get("repo", "")
                    self.github_token = config_data.get("token", "")
                    # self.github_strip_log_timestamps = config_data.get("strip_log_timestamps", self.github_strip_log_timestamps) # Gestito da app_settings
                    self.output_text_ctrl.AppendText(_("Configurazione GitHub caricata (senza password) con successo.\n"))
                    if self.github_token:
                        self.output_text_ctrl.AppendText(_("Token PAT GitHub caricato.\n"))
                    else:
                        self.output_text_ctrl.AppendText(_("Token PAT non trovato nella configurazione.\n"))
                    return bool(self.github_token)
                else:
                    self.output_text_ctrl.AppendText(
                        _("Errore: impossibile decriptare configurazione con password vuota. Configurazione corrotta o password non valida.\n")
                    )
                    return False
            except Exception as e:
                self.output_text_ctrl.AppendText(
                    _("Errore durante il caricamento silenzioso del file di configurazione: {}\n").format(e)
                )
                return False

        self.output_text_ctrl.AppendText(
            _("Token GitHub non in memoria. Richiesta password master per questa operazione...\n")
        )
        if self._prompt_and_load_github_config(called_from_startup=False):
            return bool(self.github_token)
        return False

    def _handle_delete_config_request(self, password: str, calling_dialog: wx.Dialog):
        if self._remove_github_config(password):
            calling_dialog.EndModal(wx.ID_OK)
            return True
        return False

    def _remove_github_config(self, password: str):
        print("DEBUG: _remove_github_config chiamato")
        self.output_text_ctrl.AppendText("DEBUG: _remove_github_config invocato\n")

        if not os.path.exists(self.secure_config_path):
            self.output_text_ctrl.AppendText(_("Nessuna configurazione GitHub salvata da rimuovere.\n"))
            print("DEBUG: _remove_github_config: nessun file da rimuovere")
            # Considera questo un successo perché l'obiettivo (nessuna configurazione) è raggiunto
            # Anche se il file settings.json potrebbe esistere ancora.
            # Cancelliamo settings.json se esiste, per una pulizia completa
            if os.path.exists(self.app_settings_path):
                try:
                    os.remove(self.app_settings_path)
                    self.output_text_ctrl.AppendText(f"DEBUG: File impostazioni app rimosso: {self.app_settings_path}\n")
                except Exception as e:
                    self.output_text_ctrl.AppendText(f"DEBUG: Errore rimozione {self.app_settings_path}: {e}\n")

            self.github_owner = ""
            self.github_repo = ""
            self.github_token = ""
            self.selected_run_id = None
            self.github_ask_pass_on_startup = True # Default
            self.github_strip_log_timestamps = False # Default
            self._save_app_settings() # Salva i default
            return True


        self.output_text_ctrl.AppendText(f"DEBUG: secure_config_path = {self.secure_config_path}\n")
        print(f"DEBUG: secure_config_path = {self.secure_config_path}")

        try:
            with open(self.secure_config_path, 'rb') as f:
                prefix = f.read(len(CONFIG_MAGIC_NUMBER_PREFIX))
                uuid_part = f.read(4)
                version = struct.unpack('<I', f.read(4))[0]

                self.output_text_ctrl.AppendText(f"DEBUG: magic prefix letto = {prefix}\n")
                self.output_text_ctrl.AppendText(f"DEBUG: uuid_part letto = {uuid_part}\n")
                self.output_text_ctrl.AppendText(f"DEBUG: versione file = {version}\n")
                print(f"DEBUG: magic_prefix={prefix}, uuid_part={uuid_part}, version={version}")

                if prefix != CONFIG_MAGIC_NUMBER_PREFIX:
                    self.output_text_ctrl.AppendText(_("Errore: magic prefix non corrisponde.\n"))
                    print("DEBUG: magic prefix errato")
                    return False

                expected_uuid = self.user_uuid.bytes[:4]
                if uuid_part != expected_uuid:
                    self.output_text_ctrl.AppendText(_("Errore: UUID utente non corrisponde.\n"))
                    print("DEBUG: uuid non corrisponde")
                    return False

                if version > CONFIG_FORMAT_VERSION:
                    self.output_text_ctrl.AppendText(
                        _("Errore: versione file ({}) maggiore di VERSIONE SUPPORTATA ({}).\n").format(
                            version, CONFIG_FORMAT_VERSION
                        )
                    )
                    print("DEBUG: versione file non supportata")
                    return False

                salt_len = struct.unpack('<I', f.read(4))[0]
                salt = f.read(salt_len)
                self.output_text_ctrl.AppendText(f"DEBUG: salt_len = {salt_len}\n")
                self.output_text_ctrl.AppendText(f"DEBUG: prime 8 byte di salt = {salt[:8]}\n")
                print(f"DEBUG: salt_len={salt_len}, salt[:8]={salt[:8]}")

                data_len = struct.unpack('<I', f.read(4))[0]
                encrypted_data = f.read(data_len)
                self.output_text_ctrl.AppendText(f"DEBUG: data_len = {data_len}\n")
                self.output_text_ctrl.AppendText(f"DEBUG: prime 8 byte di encrypted_data = {encrypted_data[:8]}\n")
                print(f"DEBUG: data_len={data_len}, encrypted_data[:8]={encrypted_data[:8]}")

            self.output_text_ctrl.AppendText("DEBUG: Provo a decriptare con la password fornita...\n")
            print("DEBUG: Provo a decriptare con la password fornita...")
            decrypted_json, err = self._decrypt_data(encrypted_data, salt, password)
            if err is not None or decrypted_json is None:
                self.output_text_ctrl.AppendText(
                    _("Errore decrittografia: {}. Impossibile rimuovere.\n").format(err)
                )
                print(f"DEBUG: Decrittazione fallita, errore = {err}")
                wx.MessageBox(
                    _("Password Master errata o dati corrotti. Rimozione annullata.\nErrore: {}").format(err),
                    _("Errore Rimozione"), wx.OK | wx.ICON_ERROR
                )
                return False

            os.remove(self.secure_config_path)
            self.output_text_ctrl.AppendText(_("File di configurazione criptato rimosso.\n"))
            print("DEBUG: File di configurazione rimosso")

            uuid_file = os.path.join(self._get_app_config_dir(), USER_ID_FILE_NAME)
            if os.path.exists(uuid_file):
                os.remove(uuid_file)
                self.output_text_ctrl.AppendText(f"DEBUG: File UUID utente rimosso: {uuid_file}\n")
                print(f"DEBUG: File UUID rimosso: {uuid_file}")
            else:
                self.output_text_ctrl.AppendText("DEBUG: Nessun file UUID da rimuovere\n")
                print("DEBUG: Nessun user_id.cfg da rimuovere")

            # Rimuovi anche settings.json per una pulizia completa
            if os.path.exists(self.app_settings_path):
                try:
                    os.remove(self.app_settings_path)
                    self.output_text_ctrl.AppendText(f"DEBUG: File impostazioni app rimosso: {self.app_settings_path}\n")
                except Exception as e:
                    self.output_text_ctrl.AppendText(f"DEBUG: Errore rimozione {self.app_settings_path}: {e}\n")


            self.github_owner = ""
            self.github_repo = ""
            self.github_token = ""
            self.selected_run_id = None
            self.github_ask_pass_on_startup = True # Ripristina al default
            self.github_strip_log_timestamps = False # Ripristina al default
            self.user_uuid = self._get_or_create_user_uuid() # Crea un nuovo UUID
            self._save_app_settings() # Salva i default di app_settings

            self.output_text_ctrl.AppendText(_("Configurazione GitHub, UUID utente e impostazioni app rimossi con successo.\n"))
            print("DEBUG: Configurazione interna ripulita, nuovo UUID generato, impostazioni app resettate")
            return True

        except Exception as e:
            error_str = f"{type(e).__name__}: {e}"
            self.output_text_ctrl.AppendText(
                _("Errore imprevisto durante la rimozione: {}\n").format(error_str)
            )
            print(f"DEBUG: Eccezione in _remove_github_config: {error_str}")
            wx.MessageBox(
                _("Errore durante la rimozione della configurazione: {}").format(error_str),
                _("Errore Rimozione"), wx.OK | wx.ICON_ERROR
            )
            return False

    def OnClose(self, event):
        # Arresta tutti i timer di monitoraggio attivi
        if hasattr(self, 'monitoring_timers'):
            for run_id in list(self.monitoring_timers.keys()): # Itera su una copia delle chiavi
                timer_info = self.monitoring_timers.get(run_id)
                if timer_info and timer_info['timer'].IsRunning():
                    timer_info['timer'].Stop()
                    self.output_text_ctrl.AppendText(_("Timer di monitoraggio per run ID {} arrestato.\n").format(run_id)) # Feedback
                if run_id in self.monitoring_timers: # Rimuovi la voce
                     del self.monitoring_timers[run_id]
            if self.monitoring_timers: # Se per qualche motivo non è vuoto
                 print("DEBUG: Alcuni timer potrebbero non essere stati rimossi correttamente da monitoring_timers.")
            else:
                 print("DEBUG: Tutti i timer di monitoraggio workflow arrestati e rimossi.")

        self.Destroy()
        
    def check_git_installation(self):
        try:
            process_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            subprocess.run(["git", "--version"], capture_output=True, check=True, text=True, creationflags=process_flags)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    def _handle_git_not_found(self):
        """Gestisce il caso in cui Git non sia installato, offrendo il download."""
        system = platform.system().lower()
        
        # Determina il link di download appropriato
        if system == "windows":
            download_url = "https://git-scm.com/download/win"
            system_name = "Windows"
        elif system == "darwin":  # macOS
            download_url = "https://git-scm.com/download/mac"
            system_name = "macOS"
        elif system == "linux":
            download_url = "https://git-scm.com/download/linux"
            system_name = "Linux"
        else:
            download_url = "https://git-scm.com/"
            system_name = _("il tuo sistema operativo")
        
        message = _(
            "Git non sembra essere installato o non è nel PATH di sistema.\n"
            "L'applicazione non funzionerà correttamente senza Git.\n\n"
            "Sistema rilevato: {}\n\n"
            "Vuoi aprire la pagina di download di Git per {}?"
        ).format(system_name, system_name)
        
        dlg = wx.MessageDialog(
            self, 
            message,
            _("Git Non Trovato - Download Richiesto"), 
            wx.YES_NO | wx.ICON_QUESTION
        )
        
        if dlg.ShowModal() == wx.ID_YES:
            try:
                webbrowser.open(download_url)
                self.output_text_ctrl.AppendText(
                    _("🌐 Apertura pagina di download Git: {}\n\n"
                      "📋 Istruzioni:\n"
                      "1. Scarica e installa Git dal sito web appena aperto\n"
                      "2. Riavvia questo programma dopo l'installazione\n"
                      "3. Se necessario, riavvia il computer per aggiornare il PATH\n\n"
                      "💡 Su Windows: durante l'installazione assicurati che l'opzione\n"
                      "   'Git from the command line and also from 3rd-party software' sia selezionata.\n\n").format(download_url)
                )
            except Exception as e:
                self.output_text_ctrl.AppendText(
                    _("❌ Errore nell'aprire il browser: {}\n"
                      "📋 Vai manualmente a: {}\n").format(e, download_url)
                )
                wx.MessageBox(
                    _("Impossibile aprire automaticamente il browser.\n\n"
                      "Vai manualmente a questo indirizzo per scaricare Git:\n\n"
                      "{}").format(download_url),
                    _("Apri Manualmente"), wx.OK | wx.ICON_INFORMATION
                )
        else:
            self.output_text_ctrl.AppendText(
                _("⚠️ Git non installato. Molte funzionalità non saranno disponibili.\n"
                  "📋 Per installare Git vai a: {}\n\n").format(download_url)
            )
        
        dlg.Destroy()

    def _handle_github_token_missing(self):
        """Gestisce il caso in cui il token GitHub non sia configurato."""
        message = _(
            "Token GitHub Personal Access Token (PAT) non configurato o non caricato.\n\n"
            "Molte operazioni GitHub richiedono un token per funzionare:\n"
            "• Accesso a repository privati\n"
            "• Creazione/modifica di release\n"
            "• Gestione di issue e pull request\n"
            "• Limiti API più alti\n\n"
            "Vuoi aprire la pagina GitHub per creare un nuovo token?"
        )
        
        dlg = wx.MessageDialog(
            self, 
            message,
            _("Token GitHub Mancante"), 
            wx.YES_NO | wx.ICON_QUESTION
        )
        
        if dlg.ShowModal() == wx.ID_YES:
            try:
                token_url = "https://github.com/settings/personal-access-tokens"
                webbrowser.open(token_url)
                self.output_text_ctrl.AppendText(
                    _("🌐 Apertura pagina creazione token GitHub: {}\n\n"
                    "📋 Istruzioni per creare il token:\n"
                    "1. Nella pagina appena aperta, clicca 'Generate new token'\n"
                    "2. Scegli tra 'Fine-grained tokens' (moderni) o 'Tokens (classic)'\n"
                    "3. Inserisci una descrizione (es: 'Assistente Git Desktop')\n"
                    "4. Seleziona la scadenza desiderata\n"
                    "5. Seleziona i permessi necessari:\n"
                    "   • Per Fine-grained: Contents, Actions, Metadata\n"
                    "   • Per Classic: repo, workflow\n"
                    "6. Clicca 'Generate token'\n"
                    "7. COPIA SUBITO il token (non sarà più visibile!)\n"
                    "8. Torna qui e usa '{}' per configurarlo\n\n"
                    "⚠️ IMPORTANTE: Conserva il token in un posto sicuro!\n\n").format(token_url, CMD_GITHUB_CONFIGURE)
                )
            except Exception as e:
                self.output_text_ctrl.AppendText(
                    _("❌ Errore nell'aprire il browser: {}\n"
                      "📋 Vai manualmente a: https://github.com/settings/personal-access-tokens\n").format(e)
                )
                wx.MessageBox(
                    _("Impossibile aprire automaticamente il browser.\n\n"
                      "Vai manualmente a questo indirizzo per creare un token:\n\n"
                      "https://github.com/settings/personal-access-tokens"),
                    _("Apri Manualmente"), wx.OK | wx.ICON_INFORMATION
                )
        else:
            self.output_text_ctrl.AppendText(
                _("⚠️ Token GitHub non configurato. Alcune operazioni potrebbero fallire.\n"
                  "💡 Per creare un token vai a: https://github.com/settings/personal-access-tokens\n"
                  "🔧 Usa '{}' per configurarlo una volta ottenuto.\n\n").format(CMD_GITHUB_CONFIGURE)
            )
        
        dlg.Destroy()
    def InitUI(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        repo_sizer_box = wx.StaticBoxSizer(wx.HORIZONTAL, self.panel, _("Cartella del Repository (Directory di Lavoro)"))
        repo_label = wx.StaticText(self.panel, label=_("Percorso:"))
        repo_sizer_box.Add(repo_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 5)
        self.repo_path_ctrl = wx.TextCtrl(self.panel, value=os.getcwd())
        self.repo_path_ctrl.Bind(wx.EVT_TEXT, self.OnRepoPathManuallyChanged)
        repo_sizer_box.Add(self.repo_path_ctrl, 1, wx.EXPAND | wx.RIGHT, 5)
        browse_button = wx.Button(self.panel, label=_("Sfoglia..."))
        browse_button.Bind(wx.EVT_BUTTON, self.OnBrowseRepoPath)
        repo_sizer_box.Add(browse_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        main_sizer.Add(repo_sizer_box, 0, wx.EXPAND | wx.ALL, 10)

        content_sizer = wx.BoxSizer(wx.HORIZONTAL)
        cmd_sizer_box = wx.StaticBoxSizer(wx.VERTICAL, self.panel, _("Seleziona Comando"))
        self.command_tree_ctrl = wx.TreeCtrl(self.panel, style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT | wx.TR_LINES_AT_ROOT)
        self.tree_root = self.command_tree_ctrl.AddRoot(_("Comandi"))
        first_category_node = None

        for category_key in CATEGORY_DISPLAY_ORDER:
            category_data = CATEGORIZED_COMMANDS.get(category_key)
            if category_data:
                category_node = self.command_tree_ctrl.AppendItem(self.tree_root, category_key)
                self.command_tree_ctrl.SetItemData(category_node, ("category", category_key))
                if not first_category_node:
                    first_category_node = category_node

                for command_key in category_data.get("order", []):
                    command_details = ORIGINAL_COMMANDS.get(command_key)
                    if command_details:
                        command_node = self.command_tree_ctrl.AppendItem(category_node, command_key)
                        self.command_tree_ctrl.SetItemData(command_node, ("command", category_key, command_key))

        if first_category_node and first_category_node.IsOk():
               self.command_tree_ctrl.SelectItem(first_category_node)
               self.command_tree_ctrl.EnsureVisible(first_category_node)


        self.command_tree_ctrl.Bind(wx.EVT_TREE_SEL_CHANGED, self.OnTreeItemSelectionChanged)
        self.command_tree_ctrl.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self.OnTreeItemActivated)
        cmd_sizer_box.Add(self.command_tree_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        content_sizer.Add(cmd_sizer_box, 1, wx.EXPAND | wx.RIGHT, 5)

        output_sizer_box = wx.StaticBoxSizer(wx.VERTICAL, self.panel, _("Output del Comando / Log Actions"))
        self.output_text_ctrl = wx.TextCtrl(self.panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL | wx.TE_DONTWRAP)
        mono_font = wx.Font(10, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        if mono_font.IsOk():
            self.output_text_ctrl.SetFont(mono_font)
        else: print("DEBUG: Fallimento nel creare il font Monospaced.")
        output_sizer_box.Add(self.output_text_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        content_sizer.Add(output_sizer_box, 2, wx.EXPAND, 0)

        main_sizer.Add(content_sizer, 2, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.statusBar = self.CreateStatusBar(1); self.statusBar.SetStatusText(_("Pronto."))
        self.panel.SetSizer(main_sizer); self.Layout()
        if self.command_tree_ctrl and self.command_tree_ctrl.GetSelection().IsOk(): self.OnTreeItemSelectionChanged(None)
    def OnRepoPathManuallyChanged(self, event):
        if not self.repo_path_ctrl: # Può essere chiamato durante la distruzione del widget
            event.Skip()
            return
        # Utilizziamo wx.CallLater per un piccolo debounce, evitando aggiornamenti troppo frequenti
        # mentre l'utente digita. 250ms è un ritardo ragionevole.
        # Ogni volta che l'evento scatta, resettiamo il timer.
        if hasattr(self, '_repo_path_update_timer'):
            self._repo_path_update_timer.Stop()
        
        self._repo_path_update_timer = wx.CallLater(350, self._process_repo_path_change)
        event.Skip()

    def _process_repo_path_change(self):
        """Metodo effettivo chiamato dal timer per processare il cambio di percorso."""
        if not self.repo_path_ctrl or not self.repo_path_ctrl.IsShown(): # Verifica se il widget esiste ancora
             return
        self._update_github_context_from_path()
        
    def IsTreeCtrlValid(self):
        if not hasattr(self, 'command_tree_ctrl') or not self.command_tree_ctrl: return False
        try: self.command_tree_ctrl.GetId(); return True
        except (wx.wxAssertionError, RuntimeError, AttributeError): return False

    def OnCharHook(self, event):
        if not self.IsTreeCtrlValid(): event.Skip(); return
        focused_widget = self.FindFocus()
        if focused_widget == self.command_tree_ctrl:
            keycode = event.GetKeyCode()
            if keycode == wx.WXK_SPACE: self.ShowItemInfoDialog(); return
        event.Skip()

    def ShowItemInfoDialog(self):
        if not self.IsTreeCtrlValid(): return
        selected_item_id = self.command_tree_ctrl.GetSelection()
        if not selected_item_id.IsOk(): wx.MessageBox(_("Nessun elemento selezionato."), _("Info"), wx.OK | wx.ICON_INFORMATION, self); return
        item_data = self.command_tree_ctrl.GetItemData(selected_item_id)
        item_text_display = self.command_tree_ctrl.GetItemText(selected_item_id)
        if item_data:
            item_type = item_data[0]; info_text = ""; title = _("Dettagli: {}").format(item_text_display)
            if item_type == "category":
                info_text = CATEGORIZED_COMMANDS.get(item_data[1], {}).get("info", _("Nessuna informazione disponibile per questa categoria."))
            elif item_type == "command":
                cmd_details = ORIGINAL_COMMANDS.get(item_text_display)
                if cmd_details: info_text = cmd_details.get("info", _("Nessuna informazione disponibile per questo comando."))
            if info_text: wx.MessageBox(info_text, title, wx.OK | wx.ICON_INFORMATION, self)
            else: wx.MessageBox(_("Nessuna informazione dettagliata trovata per '{}'.").format(item_text_display), _("Info"), wx.OK | wx.ICON_INFORMATION, self)
        else: wx.MessageBox(_("Nessun dato associato all'elemento '{}'.").format(item_text_display), _("Errore"), wx.OK | wx.ICON_ERROR, self)

    def OnTreeItemSelectionChanged(self, event):
        if not self.IsTreeCtrlValid(): return
        try:
            selected_item_id = self.command_tree_ctrl.GetSelection()
            if not selected_item_id.IsOk():
                if hasattr(self, 'statusBar'): self.statusBar.SetStatusText(_("Nessun elemento selezionato.")); return
        except (wx.wxAssertionError, RuntimeError): return
        item_data = self.command_tree_ctrl.GetItemData(selected_item_id)
        item_text_display = self.command_tree_ctrl.GetItemText(selected_item_id)
        status_text = _("Seleziona un comando o una categoria per maggiori dettagli.")
        if item_data:
            item_type = item_data[0]
            if item_type == "category":
                status_text = CATEGORIZED_COMMANDS.get(item_data[1], {}).get("info", _("Informazioni sulla categoria non disponibili."))
            elif item_type == "command":
                cmd_details = ORIGINAL_COMMANDS.get(item_text_display)
                if cmd_details: status_text = cmd_details.get("info", _("Informazioni sul comando non disponibili."))
        if hasattr(self, 'statusBar'): self.statusBar.SetStatusText(status_text)
        if event: event.Skip()

    def OnTreeItemActivated(self, event):
        if not self.IsTreeCtrlValid(): return
        self.output_text_ctrl.SetValue(_("Attivazione item...\n")); wx.Yield()
        try:
            activated_item_id = event.GetItem()
            if not activated_item_id.IsOk(): self.output_text_ctrl.AppendText(_("Nessun item valido selezionato per l'attivazione.\n")); return
        except (wx.wxAssertionError, RuntimeError): return

        item_data = self.command_tree_ctrl.GetItemData(activated_item_id)
        item_text_display = self.command_tree_ctrl.GetItemText(activated_item_id) # Questo è il nome tradotto

        if not item_data or item_data[0] != "command":
            if self.command_tree_ctrl.ItemHasChildren(activated_item_id):
                self.command_tree_ctrl.Toggle(activated_item_id)
                self.output_text_ctrl.AppendText(_("Categoria '{}' espansa/collassata.\n").format(item_text_display))
            else: self.output_text_ctrl.AppendText(_("'{}' non è un comando eseguibile.\n").format(item_text_display))
            return

        cmd_name_key = item_text_display # Il nome tradotto usato come chiave per ORIGINAL_COMMANDS
        cmd_details = ORIGINAL_COMMANDS.get(cmd_name_key)

        if not cmd_details:
            self.output_text_ctrl.AppendText(_("Dettagli del comando non trovati per: {}\n").format(cmd_name_key)); return

        command_type = cmd_details.get("type", "git")

        if command_type == "github":
            # Per i comandi GitHub, la logica di input (se necessaria) è gestita all'interno di ExecuteGithubCommand
            self.ExecuteGithubCommand(cmd_name_key, cmd_details)
        elif command_type == "dashboard":
            self.ExecuteDashboardCommand(cmd_name_key, cmd_details)
        elif command_type == "git":
            user_input = ""
            repo_path = self.repo_path_ctrl.GetValue() # Assicurati sia definito
            if cmd_name_key == CMD_ADD_TO_GITIGNORE:
                # ... (codice esistente per CMD_ADD_TO_GITIGNORE)
                choice_dlg = wx.SingleChoiceDialog(self, _("Cosa vuoi aggiungere a .gitignore?"), _("Selezione Tipo Elemento"), [_("File"), _("Cartella")], wx.CHOICEDLG_STYLE)
                if choice_dlg.ShowModal() == wx.ID_OK:
                    selection = choice_dlg.GetStringSelection()
                    path_to_ignore = ""
                    if selection == _("File"):
                        file_dlg = wx.FileDialog(self, _("Seleziona il file da aggiungere a .gitignore"), defaultDir=repo_path, style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
                        if file_dlg.ShowModal() == wx.ID_OK: path_to_ignore = file_dlg.GetPath()
                        file_dlg.Destroy()
                    elif selection == _("Cartella"):
                        dir_dlg = wx.DirDialog(self, _("Seleziona la cartella da aggiungere a .gitignore"), defaultPath=repo_path, style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST)
                        if dir_dlg.ShowModal() == wx.ID_OK: path_to_ignore = dir_dlg.GetPath()
                        dir_dlg.Destroy()
                    if path_to_ignore:
                        try:
                            relative_path = os.path.relpath(path_to_ignore, repo_path); user_input = relative_path.replace(os.sep, '/')
                            if os.path.isdir(path_to_ignore) and not user_input.endswith('/'): user_input += '/'
                            self.output_text_ctrl.AppendText(_("Pattern .gitignore da aggiungere: {}\n").format(user_input))
                        except ValueError: self.output_text_ctrl.AppendText(_("Errore nel calcolare il percorso relativo per: {}.\nAssicurati che sia all'interno della cartella del repository.\n").format(path_to_ignore)); choice_dlg.Destroy(); return
                    else: self.output_text_ctrl.AppendText(_("Selezione annullata.\n")); choice_dlg.Destroy(); return
                else: self.output_text_ctrl.AppendText(_("Operazione .gitignore annullata.\n")); choice_dlg.Destroy(); return
                choice_dlg.Destroy()
            elif cmd_name_key == CMD_RESTORE_FILE:
                # ... (codice esistente per CMD_RESTORE_FILE)
                file_dlg = wx.FileDialog(self, _("Seleziona il file da ripristinare allo stato dell'ultimo commit"), defaultDir=repo_path, style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
                if file_dlg.ShowModal() == wx.ID_OK:
                    path_to_restore = file_dlg.GetPath()
                    try:
                        relative_path = os.path.relpath(path_to_restore, repo_path); user_input = relative_path.replace(os.sep, '/')
                        self.output_text_ctrl.AppendText(_("File da ripristinare: {}\n").format(user_input))
                    except ValueError: self.output_text_ctrl.AppendText(_("Errore nel calcolare il percorso relativo per: {}.\nAssicurati che sia all'interno della cartella del repository.\n").format(path_to_restore)); file_dlg.Destroy(); return
                else: self.output_text_ctrl.AppendText(_("Selezione del file per il ripristino annullata.\n")); file_dlg.Destroy(); return
                file_dlg.Destroy()
            elif cmd_name_key == CMD_CHECKOUT_EXISTING:
                # Caso speciale: mostra lista di branch disponibili invece di input manuale
                available_branches = self.GetLocalBranches(repo_path)
                
                if not available_branches:
                    self.output_text_ctrl.AppendText(_("Errore: Nessun branch locale trovato o impossibile recuperare la lista dei branch.\n"))
                    return
                
                # Rimuovi il branch corrente dalla lista (opzionale)
                current_branch = self.GetCurrentBranchName(repo_path)
                if current_branch and current_branch in available_branches:
                    available_branches.remove(current_branch)
                    if not available_branches:
                        self.output_text_ctrl.AppendText(_("Errore: Sei già sull'unico branch disponibile '{}'.\n").format(current_branch))
                        return
                
                branch_dlg = wx.SingleChoiceDialog(
                    self, 
                    _("Seleziona il branch a cui passare:"), 
                    _("Passa a Branch Esistente"), 
                    available_branches, 
                    wx.CHOICEDLG_STYLE
                )
                
                if branch_dlg.ShowModal() == wx.ID_OK:
                    user_input = branch_dlg.GetStringSelection()
                    self.output_text_ctrl.AppendText(_("Branch selezionato: {}\n").format(user_input))
                else:
                    self.output_text_ctrl.AppendText(_("Selezione branch annullata.\n"))
                    branch_dlg.Destroy()
                    return
                branch_dlg.Destroy()
            elif cmd_name_key == CMD_BRANCH_D or cmd_name_key == CMD_BRANCH_FORCE_D:
                # Caso speciale: mostra lista di branch disponibili per eliminazione
                available_branches = self.GetLocalBranches(repo_path)
                
                if not available_branches:
                    self.output_text_ctrl.AppendText(_("Errore: Nessun branch locale trovato o impossibile recuperare la lista dei branch.\n"))
                    return
                
                # Rimuovi il branch corrente dalla lista per sicurezza
                current_branch = self.GetCurrentBranchName(repo_path)
                if current_branch and current_branch in available_branches:
                    available_branches.remove(current_branch)
                    if not available_branches:
                        self.output_text_ctrl.AppendText(_("Errore: Non ci sono altri branch da eliminare oltre a quello corrente '{}'.\nPer eliminare il branch corrente, passa prima a un altro branch.\n").format(current_branch))
                        return
                
                # Determina il titolo del dialogo in base al tipo di eliminazione
                if cmd_name_key == CMD_BRANCH_D:
                    dialog_title = _("Elimina Branch Locale (Sicuro)")
                    dialog_prompt = _("Seleziona il branch da eliminare (eliminazione sicura -d):")
                else:  # CMD_BRANCH_FORCE_D
                    dialog_title = _("Elimina Branch Locale (FORZATO)")
                    dialog_prompt = _("Seleziona il branch da eliminare (eliminazione FORZATA -D):")
                
                branch_dlg = wx.SingleChoiceDialog(
                    self, 
                    dialog_prompt, 
                    dialog_title, 
                    available_branches, 
                    wx.CHOICEDLG_STYLE
                )
                
                if branch_dlg.ShowModal() == wx.ID_OK:
                    user_input = branch_dlg.GetStringSelection()
                    self.output_text_ctrl.AppendText(_("Branch selezionato per eliminazione: {}\n").format(user_input))
                else:
                    self.output_text_ctrl.AppendText(_("Selezione branch per eliminazione annullata.\n"))
                    branch_dlg.Destroy()
                    return
                branch_dlg.Destroy()
            elif cmd_name_key == CMD_CHECKOUT_DETACHED:
                # Mostra dialogo di selezione commit invece di input manuale
                commit_dlg = CommitSelectionDialog(
                    self, 
                    _("Seleziona Commit per Checkout (Detached HEAD)"), 
                    repo_path
                )
                
                if commit_dlg.ShowModal() == wx.ID_OK:
                    selected_hash = commit_dlg.GetSelectedCommitHash()
                    if selected_hash:
                        user_input = selected_hash
                        self.output_text_ctrl.AppendText(_("Commit selezionato: {}\n").format(selected_hash))
                    else:
                        self.output_text_ctrl.AppendText(_("Errore: nessun commit selezionato.\n"))
                        commit_dlg.Destroy()
                        return
                else:
                    self.output_text_ctrl.AppendText(_("Selezione commit annullata.\n"))
                    commit_dlg.Destroy()
                    return
                    commit_dlg.Destroy()
            elif cmd_name_key == CMD_RESET_HARD_COMMIT:
                # Mostra dialogo di selezione commit invece di input manuale
                commit_dlg = CommitSelectionDialog(
                    self, 
                    _("Seleziona Commit per Reset --hard (ATTENZIONE!)"), 
                    repo_path
                )
                
                if commit_dlg.ShowModal() == wx.ID_OK:
                    selected_hash = commit_dlg.GetSelectedCommitHash()
                    if selected_hash:
                        user_input = selected_hash
                        self.output_text_ctrl.AppendText(_("Commit selezionato per reset: {}\n").format(selected_hash))
                    else:
                        self.output_text_ctrl.AppendText(_("Errore: nessun commit selezionato.\n"))
                        commit_dlg.Destroy()
                        return
                else:
                    self.output_text_ctrl.AppendText(_("Selezione commit annullata.\n"))
                    commit_dlg.Destroy()
                    return
                commit_dlg.Destroy()
            elif cmd_details.get("input_needed", False):
                prompt = cmd_details.get("input_label", _("Valore:"))
                placeholder = cmd_details.get("placeholder", "")
                dlg_title = _("Input per: {}").format(cmd_name_key.split('(')[0].strip())
                input_dialog = InputDialog(self, dlg_title, prompt, placeholder)
                if input_dialog.ShowModal() == wx.ID_OK:
                    user_input = input_dialog.GetValue()
                    # ... (validazioni specifiche per comandi Git esistenti) ...
                    if cmd_name_key == CMD_LOG_CUSTOM:
                        try:
                            num = int(user_input);
                            if num <= 0: self.output_text_ctrl.AppendText(_("Errore: Il numero di commit deve essere un intero positivo.\n")); input_dialog.Destroy(); return
                            user_input = str(num)
                        except ValueError: self.output_text_ctrl.AppendText(_("Errore: '{}' non è un numero valido.\n").format(user_input)); input_dialog.Destroy(); return
                    elif cmd_name_key in [CMD_TAG_LIGHTWEIGHT, CMD_AMEND_COMMIT, CMD_GREP, CMD_RESET_TO_REMOTE]:
                          if not user_input: self.output_text_ctrl.AppendText(_("Errore: Questo comando richiede un input.\n")); input_dialog.Destroy(); return
                    elif cmd_name_key != CMD_LS_FILES: # LS_FILES può avere input vuoto
                        is_commit = cmd_name_key == CMD_COMMIT
                        if not user_input and is_commit: # Commit può avere messaggio vuoto con conferma
                            if wx.MessageBox(_("Il messaggio di commit è vuoto. Vuoi procedere comunque?"), _("Conferma Commit Vuoto"), wx.YES_NO | wx.ICON_QUESTION) != wx.ID_YES:
                                self.output_text_ctrl.AppendText(_("Creazione del commit annullata.\n")); input_dialog.Destroy(); return
                        # Per altri comandi Git che richiedono input e non hanno placeholder vuoto (o non sono LS_FILES)
                        elif not user_input and not is_commit and placeholder == "" and cmd_name_key != CMD_LS_FILES :
                            self.output_text_ctrl.AppendText(_("Input richiesto per questo comando.\n")); input_dialog.Destroy(); return
                else:
                    self.output_text_ctrl.AppendText(_("Azione annullata dall'utente.\n")); input_dialog.Destroy(); return
                input_dialog.Destroy()
            self.ExecuteGitCommand(cmd_name_key, cmd_details, user_input)
        else:
            self.output_text_ctrl.AppendText(_("Tipo di comando non riconosciuto: {}\n").format(command_type))
            
    def ExecuteGitCommand(self, command_name_original_translated, command_details, user_input_val):
        self.output_text_ctrl.AppendText(_("Esecuzione comando Git: {}...\n").format(command_name_original_translated))
        if user_input_val and command_details.get("input_needed") and \
           command_name_original_translated not in [CMD_ADD_TO_GITIGNORE, CMD_RESTORE_FILE]:
               self.output_text_ctrl.AppendText(_("Input fornito: {}\n").format(user_input_val))
        repo_path = self.repo_path_ctrl.GetValue()
        self.output_text_ctrl.AppendText(_("Cartella Repository: {}\n\n").format(repo_path)); wx.Yield()
        if not self.git_available and command_name_original_translated != CMD_ADD_TO_GITIGNORE:
            self.output_text_ctrl.AppendText(_("Errore: Git non sembra essere installato o accessibile nel PATH di sistema.\n")); wx.MessageBox(_("Git non disponibile."), _("Errore Git"), wx.OK | wx.ICON_ERROR); return
        if not os.path.isdir(repo_path): self.output_text_ctrl.AppendText(_("Errore: La cartella specificata '{}' non è una directory valida.\n").format(repo_path)); return

        is_special_no_repo_check = command_name_original_translated in [CMD_CLONE, CMD_INIT_REPO]
        is_gitignore = command_name_original_translated == CMD_ADD_TO_GITIGNORE
        is_ls_files = command_name_original_translated == CMD_LS_FILES

        if not is_special_no_repo_check and not is_gitignore and not is_ls_files:
            if not os.path.isdir(os.path.join(repo_path, ".git")):
                self.output_text_ctrl.AppendText(_("Errore: La cartella '{}' non sembra essere un repository Git valido (manca la sottocartella .git).\n").format(repo_path)); return
        elif is_gitignore:
            if not os.path.isdir(os.path.join(repo_path, ".git")):
                   self.output_text_ctrl.AppendText(_("Avviso: La cartella '{}' non sembra essere un repository Git. Il file .gitignore verrà creato/modificato, ma Git potrebbe non utilizzarlo fino all'inizializzazione del repository ('{}').\n").format(repo_path, CMD_INIT_REPO))

        if command_details.get("confirm"):
            msg = command_details["confirm"].replace("{input_val}", user_input_val if user_input_val else _("VALORE_NON_SPECIFICATO"))
            style = wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING; title_confirm = _("Conferma Azione")
            if "ATTENZIONE MASSIMA" in command_details.get("info","") or "CONFERMA ESTREMA" in msg:
                style = wx.YES_NO | wx.NO_DEFAULT | wx.ICON_ERROR; title_confirm = _("Conferma Azione PERICOLOSA!")
            dlg = wx.MessageDialog(self, msg, title_confirm, style)
            if dlg.ShowModal() != wx.ID_YES: self.output_text_ctrl.AppendText(_("Operazione annullata dall'utente.\n")); dlg.Destroy(); return
            dlg.Destroy()

        full_output = ""; success = True; process_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        cmds_to_run = []

        if command_name_original_translated == CMD_ADD_TO_GITIGNORE:
            if not user_input_val: self.output_text_ctrl.AppendText(_("Errore: Nessun pattern fornito per .gitignore.\n")); return
            gitignore_path = os.path.join(repo_path, ".gitignore")
            try:
                entry_exists = False
                if os.path.exists(gitignore_path):
                    with open(gitignore_path, 'r', encoding='utf-8') as f_read:
                        if user_input_val.strip() in (line.strip() for line in f_read): entry_exists = True
                if entry_exists:
                    full_output += _("L'elemento '{}' è già presente in .gitignore.\n").format(user_input_val)
                else:
                    with open(gitignore_path, 'a', encoding='utf-8') as f_append:
                        if os.path.exists(gitignore_path) and os.path.getsize(gitignore_path) > 0:
                             with open(gitignore_path, 'rb+') as f_nl_check: # Check last char
                                f_nl_check.seek(-1, os.SEEK_END)
                                if f_nl_check.read() != b'\n':
                                    f_append.write('\n') # Add newline if not present
                        f_append.write(f"{user_input_val.strip()}\n")
                    full_output += _("'{}' aggiunto correttamente a .gitignore.\n").format(user_input_val)
                success = True
            except Exception as e: full_output += _("Errore durante la scrittura nel file .gitignore: {}\n").format(e); success = False
        elif command_name_original_translated == CMD_LS_FILES:
            try:
                git_check_proc = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=repo_path, capture_output=True, text=True, creationflags=process_flags)
                if git_check_proc.returncode != 0 or git_check_proc.stdout.strip() != "true":
                    full_output += _("Errore: La cartella '{}' non è un repository Git valido o non sei nella directory principale del progetto.\n").format(repo_path)
                    success = False
                else:
                    process = subprocess.run(["git", "ls-files"], cwd=repo_path, capture_output=True, text=True, check=True, encoding='utf-8', errors='replace', creationflags=process_flags)
                    out = process.stdout
                    if user_input_val:
                        lines = out.splitlines(); glob_p = user_input_val if any(c in user_input_val for c in ['*', '?', '[']) else f"*{user_input_val}*"
                        filtered = [l for l in lines if fnmatch.fnmatchcase(l.lower(), glob_p.lower())]
                        full_output += _("--- Risultati per il pattern '{}' ---\n").format(user_input_val) + ("\n".join(filtered) + "\n" if filtered else _("Nessun file trovato corrispondente al pattern.\n"))
                    else: full_output += _("--- Tutti i file tracciati da Git nel repository ---\n{}").format(out)
                    if process.stderr: full_output += _("--- Messaggi/Errori da 'git ls-files' ---\n{}\n").format(process.stderr)
                    success = process.returncode == 0
            except subprocess.CalledProcessError as e:
                full_output += _("Errore durante l'esecuzione di 'git ls-files': {}\n").format(e.stderr or e.stdout or str(e))
                if "not a git repository" in (e.stderr or "").lower():
                    full_output += _("La cartella '{}' non sembra essere un repository Git valido.\n").format(repo_path)
                success = False
            except Exception as e: full_output += _("Errore imprevisto durante la ricerca dei file: {}\n").format(e); success = False
        else:
            if command_name_original_translated == CMD_TAG_LIGHTWEIGHT:
                parts = user_input_val.split(maxsplit=1)
                if len(parts) == 1 and parts[0]: cmds_to_run = [["git", "tag", parts[0]]]
                elif len(parts) >= 2 and parts[0]: cmds_to_run = [["git", "tag", parts[0], parts[1]]]
                else: self.output_text_ctrl.AppendText(_("Errore: Input per il tag non valido. Fornire almeno il nome del tag.\n")); return
            else:
                for tmpl in command_details.get("cmds", []): cmds_to_run.append([p.replace("{input_val}", user_input_val) for p in tmpl])

            if not cmds_to_run:
                if command_name_original_translated != CMD_TAG_LIGHTWEIGHT: # Tag può non avere cmd se input errato
                    self.output_text_ctrl.AppendText(_("Nessun comando specifico da eseguire per questa azione.\n"))
                return

            for i, cmd_parts in enumerate(cmds_to_run):
                try:
                    proc = subprocess.run(cmd_parts, cwd=repo_path, capture_output=True, text=True, check=False, encoding='utf-8', errors='replace', creationflags=process_flags)
                    if proc.stdout: full_output += _("--- Output ({}) ---\n{}\n").format(' '.join(cmd_parts), proc.stdout)
                    if proc.stderr: full_output += _("--- Messaggi/Errori ({}) ---\n{}\n").format(' '.join(cmd_parts), proc.stderr)

                    if proc.returncode != 0:
                        full_output += _("\n!!! Comando {} fallito con codice di uscita: {} !!!\n").format(' '.join(cmd_parts), proc.returncode)
                        success = False

                        is_no_upstream_error = (
                            command_name_original_translated == CMD_PUSH and
                            proc.returncode == 128 and # Specific error code for some push failures
                            ("has no upstream branch" in proc.stderr.lower() or "no configured push destination" in proc.stderr.lower())
                        )
                        if is_no_upstream_error:
                            self.output_text_ctrl.AppendText(full_output)
                            self.HandlePushNoUpstream(repo_path, proc.stderr)
                            return

                        if command_name_original_translated == CMD_MERGE and "conflict" in (proc.stdout + proc.stderr).lower():
                            self.output_text_ctrl.AppendText(full_output)
                            self.HandleMergeConflict(repo_path)
                            return
                        # Gestione checkout bloccato da modifiche locali
                        is_checkout_blocked_error = (
                            command_name_original_translated in [CMD_CHECKOUT_DETACHED, CMD_RESET_HARD_COMMIT] and
                            proc.returncode == 1 and
                            ("would be overwritten by checkout" in proc.stderr.lower() or 
                             "please commit your changes or stash them" in proc.stderr.lower())
                        )
                        
                        if is_checkout_blocked_error:
                            self.output_text_ctrl.AppendText(full_output)
                            
                            # Estrai il commit target dal comando
                            target_commit = user_input_val if user_input_val else "unknown"
                            
                            # Gestisci il conflitto
                            if self.HandleCheckoutWithLocalChanges(repo_path, target_commit, proc.stderr):
                                # Se la gestione ha avuto successo, non eseguire il resto del metodo
                                return
                            else:
                                # Se l'utente ha annullato o c'è stato un errore, continua con il flusso normale
                                return

                        if command_name_original_translated == CMD_BRANCH_D and "not fully merged" in (proc.stdout + proc.stderr).lower():
                            self.output_text_ctrl.AppendText(full_output)
                            self.HandleBranchNotMerged(repo_path, user_input_val)
                            return
                        break # Interrompi l'esecuzione di comandi concatenati se uno fallisce
                except Exception as e:
                    full_output += _("Errore durante l'esecuzione di {}: {}\n").format(' '.join(cmd_parts), e); success = False; break

        self.output_text_ctrl.AppendText(full_output)

        if success:
            if command_name_original_translated == CMD_ADD_TO_GITIGNORE:
                self.output_text_ctrl.AppendText(_("\nOperazione .gitignore completata con successo.\n"))
            elif command_name_original_translated == CMD_LS_FILES:
                self.output_text_ctrl.AppendText(_("\nRicerca file completata.\n"))
                # Per LS_FILES non mostriamo popup (è solo una ricerca)
            else:
                self.output_text_ctrl.AppendText(_("\nComando/i completato/i con successo.\n"))
                # Mostra popup di successo
                self.ShowOperationResult(
                    operation_name=command_name_original_translated,
                    success=True,
                    output=full_output
                )
        else:
            if command_name_original_translated == CMD_ADD_TO_GITIGNORE:
                self.output_text_ctrl.AppendText(_("\nErrore durante l'aggiornamento del file .gitignore.\n"))
                self.ShowOperationResult(
                    operation_name=command_name_original_translated,
                    success=False,
                    error_output=full_output
                )
            elif command_name_original_translated == CMD_LS_FILES:
                self.output_text_ctrl.AppendText(_("\nErrore durante la ricerca dei file.\n"))
                self.ShowOperationResult(
                    operation_name=command_name_original_translated,
                    success=False,
                    error_output=full_output
                )
            elif cmds_to_run: # Solo se c'erano comandi da eseguire
                self.output_text_ctrl.AppendText(_("\nEsecuzione (o parte di essa) fallita o con errori. Controllare l'output per i dettagli.\n"))
                self.ShowOperationResult(
                    operation_name=command_name_original_translated,
                    success=False,
                    error_output=full_output
                )

        if success and command_name_original_translated == CMD_AMEND_COMMIT:
            dlg = wx.MessageDialog(self, _("Commit modificato con successo.\n\n"
                                 "ATTENZIONE: Se questo commit era già stato inviato (push) a un repository condiviso, "
                                 "forzare il push (push --force) sovrascriverà la cronologia sul server. "
                                 "Questo può creare problemi per altri collaboratori.\n\n"
                                 "Vuoi tentare un push forzato a 'origin' ora?"),
                                 _("Push Forzato Dopo Amend?"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING)
            if dlg.ShowModal() == wx.ID_YES:
                self.output_text_ctrl.AppendText(_("\nTentativo di push forzato a 'origin' in corso...\n")); wx.Yield()
                self.RunSingleGitCommand(["git", "push", "--force", "origin"], repo_path, _("Push Forzato dopo Amend"))
            else: self.output_text_ctrl.AppendText(_("\nPush forzato non eseguito.\n"))
            dlg.Destroy()

        if success and command_name_original_translated == CMD_CLONE and user_input_val:
            try:
                repo_name = user_input_val.split('/')[-1]
                if repo_name.endswith(".git"): repo_name = repo_name[:-4]
                if repo_name:
                    new_repo_path = os.path.join(repo_path, repo_name) # Assumendo che clone avvenga nella cartella corrente
                    if os.path.isdir(new_repo_path):
                        self.repo_path_ctrl.SetValue(new_repo_path)
                        self.output_text_ctrl.AppendText(_("\nPercorso della cartella repository aggiornato a: {}\n").format(new_repo_path))
            except Exception as e:
                self.output_text_ctrl.AppendText(_("\nAvviso: impossibile aggiornare automaticamente il percorso dopo il clone: {}.\nSi prega di selezionare manualmente la nuova cartella del repository se necessario.\n").format(e))

    def _get_github_repo_details_from_current_path(self):
        repo_path = self.repo_path_ctrl.GetValue()
        if not os.path.isdir(os.path.join(repo_path, ".git")):
            return None, None

        try:
            process_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            proc = subprocess.run(["git", "remote", "get-url", "origin"], cwd=repo_path,
                                    capture_output=True, text=True, check=True,
                                    encoding='utf-8', errors='replace', creationflags=process_flags)
            origin_url = proc.stdout.strip()
            match = re.search(r'github\.com[/:]([^/]+)/([^/.]+)(\.git)?$', origin_url)
            if match:
                owner = match.group(1)
                repo = match.group(2)
                return owner, repo
        except (subprocess.CalledProcessError, FileNotFoundError, Exception) as e:
            print(f"DEBUG: Impossibile ottenere URL di origin o analizzarlo: {e}")
        return None, None
    def _update_github_context_from_path(self):
        """
        Tenta di aggiornare self.github_owner e self.github_repo
        in base al percorso corrente in self.repo_path_ctrl.
        Resetta self.selected_run_id se il contesto GitHub cambia o diventa non valido.
        """
        current_repo_dir_from_ctrl = self.repo_path_ctrl.GetValue()

        # Prevenire aggiornamenti se il path non è cambiato e avevamo già un contesto valido
        if hasattr(self, '_last_processed_path_for_context') and \
           self._last_processed_path_for_context == current_repo_dir_from_ctrl and \
           self.github_owner and self.github_repo:
            return

        previous_owner = self.github_owner
        previous_repo = self.github_repo
        context_changed = False

        if not os.path.isdir(current_repo_dir_from_ctrl):
            if hasattr(self, '_last_processed_path_for_context') and self._last_processed_path_for_context != current_repo_dir_from_ctrl:
                if previous_owner or previous_repo: # Se c'era un contesto prima
                    self.output_text_ctrl.AppendText(
                        _("AVVISO: Il percorso del repository '{}' non è una directory valida.\n"
                          "Le operazioni GitHub potrebbero riferirsi al contesto precedente ({} hefty{}).\n"
                          "La selezione precedente di un'esecuzione workflow è stata resettata.\n").format(
                            current_repo_dir_from_ctrl, previous_owner, previous_repo
                        )
                    )
                self.selected_run_id = None
                context_changed = True # Il path è cambiato verso un non-repo
            self._last_processed_path_for_context = current_repo_dir_from_ctrl
            return # Non possiamo derivare da un percorso non valido

        derived_owner, derived_repo = self._get_github_repo_details_from_current_path()

        if derived_owner and derived_repo:
            if self.github_owner != derived_owner or self.github_repo != derived_repo:
                self.github_owner = derived_owner
                self.github_repo = derived_repo
                self.output_text_ctrl.AppendText(
                    _("Contesto GitHub Actions/Release aggiornato automaticamente dal percorso '{}':\n"
                      "  Nuovo Proprietario: {}\n"
                      "  Nuovo Repository: {}\n"
                      "Il token PAT (se caricato) rimane invariato.\n").format(
                        current_repo_dir_from_ctrl, self.github_owner, self.github_repo)
                )
                context_changed = True
        else: # Derivazione fallita (es. non è un repo GitHub, o nessun remote 'origin' con URL riconoscibile)
            # Se il path è cambiato rispetto all'ultima volta E avevamo un contesto GitHub prima,
            # significa che il vecchio contesto potrebbe non essere più rilevante.
            if hasattr(self, '_last_processed_path_for_context') and self._last_processed_path_for_context != current_repo_dir_from_ctrl:
                if previous_owner or previous_repo: # Se c'era un contesto GitHub
                    self.output_text_ctrl.AppendText(
                        _("AVVISO: Impossibile derivare automaticamente il proprietario/repository GitHub dal percorso '{}'.\n"
                          "Le operazioni GitHub continueranno ad usare il contesto precedentemente configurato/derivato: {}/{}.\n"
                          "Se questo non è corretto, usa il comando '{}' per aggiornare manualmente la configurazione.\n").format(
                            current_repo_dir_from_ctrl, previous_owner, previous_repo, CMD_GITHUB_CONFIGURE
                        )
                    )
                context_changed = True # Il path è cambiato, ma la derivazione è fallita
        
        if context_changed:
            if self.selected_run_id is not None:
                self.output_text_ctrl.AppendText(_("La selezione precedente di un'esecuzione workflow è stata resettata a causa del cambio di contesto del repository.\n"))
                self.selected_run_id = None

        self._last_processed_path_for_context = current_repo_dir_from_ctrl
    def get_available_workflows(self):
        """Recupera la lista dei workflow disponibili nel repository."""
        if not self.github_owner or not self.github_repo:
            return []
        
        headers = {"Accept": "application/vnd.github.v3+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
        
        workflows_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/actions/workflows"
        
        try:
            response = requests.get(workflows_url, headers=headers, timeout=10)
            response.raise_for_status()
            workflows_data = response.json()
            
            workflows = []
            for workflow in workflows_data.get('workflows', []):
                if workflow.get('state') == 'active':  # Solo workflow attivi
                    workflows.append({
                        'id': workflow['id'],
                        'name': workflow['name'],
                        'path': workflow['path'],
                        'badge_url': workflow.get('badge_url', ''),
                        'html_url': workflow.get('html_url', '')
                    })
            return workflows
        except Exception as e:
            print(f"DEBUG_WORKFLOWS: Errore recupero workflow: {e}")
            return []
    def auto_find_and_monitor_latest_run(self, workflow_name=None): # Firma modificata
        """Trova automaticamente l'ultima run e avvia il monitoraggio."""
        try:
            api_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/actions/runs"
            headers = {"Accept": "application/vnd.github.v3+json", "X-GitHub-Api-Version": "2022-11-28"}
            if self.github_token:
                headers["Authorization"] = f"Bearer {self.github_token}"

            params = {'per_page': 5} # Recupera solo le prime 5 esecuzioni più recenti
            response = requests.get(api_url, headers=headers, params=params, timeout=10)
            response.raise_for_status() # Solleva un'eccezione per errori HTTP (4xx o 5xx)

            runs_data = response.json()
            latest_runs = runs_data.get('workflow_runs', [])

            if latest_runs:
                latest_run = latest_runs[0]  # La più recente è la prima nella lista
                run_id = latest_run['id']
                # 1. Definire 'status' PRIMA del suo utilizzo
                status = latest_run.get('status', 'unknown')

                # 2. Definire il nome del workflow da monitorare/visualizzare.
                #    Usa 'workflow_name' se è stato passato (dal trigger manuale),
                #    altrimenti usa il nome dell'esecuzione specifica dall'API.
                actual_workflow_name_to_monitor = workflow_name if workflow_name else latest_run.get('name', _('(Nome Workflow Sconosciuto)'))

                # 3. Ora si possono usare 'actual_workflow_name_to_monitor', 'run_id', e 'status'
                self.output_text_ctrl.AppendText(
                    _("🎯 Trovata esecuzione recente: '{}' (ID: {}, Status: {})\n").format(actual_workflow_name_to_monitor, run_id, status)
                )

                # Controlla se la run è in uno stato che giustifica il monitoraggio
                if status.lower() in ['queued', 'in_progress', 'waiting', 'requested', 'pending']:
                    self.selected_run_id = run_id # Salva l'ID della run selezionata per il monitoraggio
                    # 4. Impostare 'self.monitoring_workflow_name' che verrà usato dal timer
                    self.monitoring_workflow_name = actual_workflow_name_to_monitor
                    self.start_monitoring_run(run_id, self.github_owner, self.github_repo)
                    self.output_text_ctrl.AppendText(_("🔄 Monitoraggio automatico avviato!\n"))
                else:
                    # Se la run è già completata o in uno stato terminale
                    self.output_text_ctrl.AppendText(_("ℹ️ Il workflow è già terminato ({})\n").format(status))
            else:
                # Nessuna esecuzione trovata per il repository/branch specificato (implicito nei parametri API)
                self.output_text_ctrl.AppendText(_("❌ Nessuna esecuzione recente trovata\n"))

        except requests.exceptions.RequestException as e_req: # Gestisce specificamente errori di rete/HTTP
            self.output_text_ctrl.AppendText(_("❌ Errore di rete/API nel recupero automatico: {}\n").format(e_req))
        except Exception as e: # Gestisce altre eccezioni impreviste
            # Se 'e' fosse NameError("name 'status' is not defined"), indicherebbe un problema di logica nel blocco try.
            self.output_text_ctrl.AppendText(_("❌ Errore imprevisto nel recupero automatico: {}\n").format(e))
    def verify_workflow_cancellation(self, run_id, run_name):
        """Verifica lo stato di un workflow dopo la cancellazione."""
        try:
            headers = {"Accept": "application/vnd.github.v3+json", "X-GitHub-Api-Version": "2022-11-28"}
            if self.github_token:
                headers["Authorization"] = f"Bearer {self.github_token}"
            
            status_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/actions/runs/{run_id}"
            response = requests.get(status_url, headers=headers, timeout=10)
            response.raise_for_status()
            
            run_data = response.json()
            current_status = run_data.get('status', 'unknown')
            current_conclusion = run_data.get('conclusion', 'N/D')
            
            self.output_text_ctrl.AppendText(
                _("🔍 Verifica stato workflow '{}': Status={}, Conclusion={}\n").format(
                    run_name, current_status, current_conclusion
                )
            )
            
            if current_status == 'completed' and current_conclusion == 'cancelled':
                self.output_text_ctrl.AppendText(_("✅ Workflow effettivamente cancellato!\n"))
            elif current_status in ['in_progress', 'queued']:
                self.output_text_ctrl.AppendText(_("⏳ Workflow ancora in esecuzione, cancellazione in corso...\n"))
            else:
                self.output_text_ctrl.AppendText(_("ℹ️ Stato workflow: {}\n").format(current_status))
                
        except Exception as e:
            self.output_text_ctrl.AppendText(_("❌ Errore verifica stato: {}\n").format(e))
            
    def ExecuteGithubCommand(self, command_name_key, command_details):
        self.output_text_ctrl.AppendText(f"DEBUG: ExecuteGithubCommand chiamato!\n")
        self.output_text_ctrl.AppendText(f"DEBUG: command_name_key ricevuto = '{command_name_key}'\n")
        self.output_text_ctrl.AppendText(f"DEBUG: type(command_name_key) = {type(command_name_key)}\n")
        self.output_text_ctrl.AppendText(f"DEBUG: command_details = {command_details}\n")
        wx.Yield()
    
        self.output_text_ctrl.AppendText(_("Esecuzione comando GitHub: {}...\n").format(command_name_key))

        if command_name_key == CMD_GITHUB_CONFIGURE:
            dlg = GitHubConfigDialog(self, _("Configurazione GitHub Actions"),
                                     self.github_owner,
                                     self.github_repo,
                                     bool(self.github_token),
                                     self.github_ask_pass_on_startup,
                                     self.github_strip_log_timestamps,
                                     self.github_monitoring_beep)
            
            if dlg.ShowModal() == wx.ID_OK:
                values = dlg.GetValues()
                dialog_password = values["password"]
                new_token_val = values["token"]
                new_owner_val = values["owner"]
                new_repo_val = values["repo"]
                new_ask_pass_startup = values["ask_pass_on_startup"]
                new_strip_timestamps = values["strip_log_timestamps"]
                new_monitoring_beep = values["monitoring_beep"]

                if not new_owner_val or not new_repo_val:
                    self.output_text_ctrl.AppendText(_("Proprietario e Nome Repository sono obbligatori.\n"))
                    wx.MessageBox(_("Proprietario e Nome Repository non possono essere vuoti."), _("Errore Configurazione"), wx.OK | wx.ICON_ERROR, self)
                    dlg.Destroy()
                    return

                self.github_ask_pass_on_startup = new_ask_pass_startup
                self.github_strip_log_timestamps = new_strip_timestamps
                self.github_monitoring_beep = new_monitoring_beep
                self._save_app_settings()

                # MODIFICA: Preserva il token esistente se il campo è vuoto
                if new_token_val:
                    # L'utente ha inserito un nuovo token
                    token_to_save = new_token_val
                    token_action_message = _("Token aggiornato")
                elif self.github_token:
                    # L'utente ha lasciato vuoto il campo ma c'è già un token salvato
                    token_to_save = self.github_token
                    token_action_message = _("Token esistente mantenuto")
                else:
                    # Nessun token inserito e nessun token esistente
                    token_to_save = ""
                    token_action_message = _("Nessun token configurato")

                self.output_text_ctrl.AppendText(_("Azione token: {}\n").format(token_action_message))

                if self._save_github_config(new_owner_val, new_repo_val, token_to_save,
                                            dialog_password, new_ask_pass_startup, new_strip_timestamps, new_monitoring_beep):
                    self.output_text_ctrl.AppendText(_("Configurazione GitHub salvata/aggiornata su file.\n"))
                    if self.github_owner != new_owner_val or self.github_repo != new_repo_val:
                        self.selected_run_id = None
                        self.output_text_ctrl.AppendText(_("Selezione esecuzione workflow resettata.\n"))
                    self._last_processed_path_for_context = self.repo_path_ctrl.GetValue()
                else:
                    self.output_text_ctrl.AppendText(_("Salvataggio configurazione GitHub su file fallito o non eseguito.\n"))
                    made_in_memory_changes = False
                    if self.github_owner != new_owner_val:
                        self.github_owner = new_owner_val
                        made_in_memory_changes = True
                    if self.github_repo != new_repo_val:
                        self.github_repo = new_repo_val
                        made_in_memory_changes = True
                    if self.github_token != token_to_save:
                        self.github_token = token_to_save
                        made_in_memory_changes = True
                    if made_in_memory_changes:
                        self.output_text_ctrl.AppendText(_("I dettagli GitHub sono stati aggiornati in memoria per la sessione corrente.\n"))
                        if (self.github_owner != new_owner_val or self.github_repo != new_repo_val) and (new_owner_val and new_repo_val):
                            self.selected_run_id = None
                            self.output_text_ctrl.AppendText(_("Selezione esecuzione workflow resettata.\n"))
                        self._last_processed_path_for_context = self.repo_path_ctrl.GetValue()
                
                self.output_text_ctrl.AppendText(_("Configurazione GitHub attuale (in memoria):\nProprietario: {}\nRepository: {}\nToken PAT: {}\nRichiedi pass all'avvio: {}\nRimuovi Timestamp Log: {}\n").format(
                    self.github_owner if self.github_owner else _("Non impostato"),
                    self.github_repo if self.github_repo else _("Non impostato"),
                    _("Presente") if self.github_token else _("Non presente/Non caricato"),
                    self.github_ask_pass_on_startup,
                    self.github_strip_log_timestamps
                ))
            else:
                self.output_text_ctrl.AppendText(_("Configurazione GitHub annullata.\n"))
            dlg.Destroy()
            return

        if not self.github_owner or not self.github_repo:
            self.output_text_ctrl.AppendText(
                _("ERRORE: Proprietario e/o nome del Repository GitHub non sono attualmente impostati.\n"
                  "Assicurati che il percorso corrente punti a un repository GitHub con un remoto 'origin' valido e riconoscibile, "
                  "oppure imposta manualmente i dettagli usando il comando '{}'.\n").format(CMD_GITHUB_CONFIGURE)
            )
            return

        if not self._ensure_github_config_loaded() and command_name_key not in [CMD_GITHUB_LIST_WORKFLOW_RUNS]:
            self._handle_github_token_missing()
            return
        headers = {"Accept": "application/vnd.github.v3+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
        elif command_name_key not in [CMD_GITHUB_LIST_WORKFLOW_RUNS]:
            if command_name_key in [CMD_GITHUB_CREATE_RELEASE, CMD_GITHUB_DELETE_RELEASE]:
                self.output_text_ctrl.AppendText(_("ERRORE: Token di Accesso Personale GitHub non configurato o non caricato. È necessario per questa operazione.\nUsa '{}' per configurarlo.\n").format(CMD_GITHUB_CONFIGURE))
                return
            self.output_text_ctrl.AppendText(_("ATTENZIONE: Token GitHub non disponibile. L'operazione potrebbe fallire o avere funzionalità limitate, specialmente per repository privati o per creare/modificare risorse.\n"))

        if command_name_key == CMD_GITHUB_CREATE_RELEASE:
            dlg = CreateReleaseDialog(self, _("Crea Nuova Release GitHub"))
            if dlg.ShowModal() == wx.ID_OK:
                values = dlg.GetValues()
                tag_name = values["tag_name"]
                release_name = values["release_name"]
                release_body = values["release_body"]
                files_to_upload = values["files_to_upload"]

                if not tag_name or not release_name:
                    self.output_text_ctrl.AppendText(_("Tag o Titolo della release non validi. Operazione annullata.\n"))
                    dlg.Destroy()
                    return

                api_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/releases"
                payload = {
                    "tag_name": tag_name,
                    "name": release_name,
                    "body": release_body,
                    "draft": False,
                    "prerelease": False
                }
                self.output_text_ctrl.AppendText(f"Invio richiesta per creare la release '{release_name}' (tag: {tag_name}) su {self.github_owner}/{self.github_repo}...\n")
                wx.Yield()
                try:
                    response = requests.post(api_url, headers=headers, data=json.dumps(payload), timeout=15)
                    response.raise_for_status()
                    release_info = response.json()
                    self.output_text_ctrl.AppendText(_("Release creata con successo: {}\n").format(release_info.get('html_url')))

                    upload_url_template = release_info.get("upload_url", "")
                    if upload_url_template and files_to_upload:
                        upload_url_base = upload_url_template.split("{")[0]
                        for fpath in files_to_upload:
                            filename = os.path.basename(fpath)
                            params_upload = {"name": filename}
                            self.output_text_ctrl.AppendText(_("Upload asset: '{}'...\n").format(filename))
                            wx.Yield()
                            try:
                                with open(fpath, "rb") as f:
                                    file_data = f.read()
                                headers_asset_upload = headers.copy()
                                headers_asset_upload["Content-Type"] = "application/octet-stream"
                                response_asset = requests.post(upload_url_base, headers=headers_asset_upload, params=params_upload, data=file_data, timeout=120)
                                response_asset.raise_for_status()
                                asset_info = response_asset.json()
                                self.output_text_ctrl.AppendText(_("Asset '{}' caricato: {}\n").format(filename, asset_info.get('browser_download_url')))
                            except requests.exceptions.RequestException as e_asset:
                                self.output_text_ctrl.AppendText(_("ERRORE upload asset '{}': {}\n").format(filename, e_asset))
                                if hasattr(e_asset, 'response') and e_asset.response is not None:
                                    self.output_text_ctrl.AppendText(_("Dettagli errore API asset: {}\n").format(e_asset.response.text[:500]))
                            except IOError as e_io:
                                self.output_text_ctrl.AppendText(_("ERRORE lettura file asset '{}': {}\n").format(filename, e_io))
                except requests.exceptions.RequestException as e:
                    self.output_text_ctrl.AppendText(_("ERRORE API GitHub (creazione release): {}\n").format(e))
                    if hasattr(e, 'response') and e.response is not None:
                        try:
                            error_details = e.response.json()
                            self.output_text_ctrl.AppendText(_("Dettagli errore API: {}\n").format(json.dumps(error_details, indent=2)))
                        except json.JSONDecodeError:
                            self.output_text_ctrl.AppendText(_("Dettagli errore API (testo): {}\n").format(e.response.text[:500]))
                except Exception as e_generic:
                    self.output_text_ctrl.AppendText(_("ERRORE imprevisto durante creazione release: {}\n").format(e_generic))
            else:
                self.output_text_ctrl.AppendText(_("Creazione Release annullata dall'utente.\n"))
            dlg.Destroy()
            return
        elif command_name_key == CMD_GITHUB_EDIT_RELEASE:
            # Recupera lista delle release esistenti
            self.output_text_ctrl.AppendText(_("Recupero elenco release da GitHub per {}/{}\n").format(self.github_owner, self.github_repo))
            wx.Yield()
            
            releases_api_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/releases"
            try:
                response_list = requests.get(releases_api_url, headers=headers, params={"per_page": 50}, timeout=15)
                response_list.raise_for_status()
                releases_data = response_list.json()

                if not releases_data:
                    self.output_text_ctrl.AppendText(_("Nessuna release trovata per il repository {}/{}.\n").format(self.github_owner, self.github_repo))
                    return

                # Crea lista di scelte per l'utente
                release_choices = []
                releases_map = {}
                for rel in releases_data:
                    name = rel.get('name', _('Senza nome'))
                    tag = rel.get('tag_name', 'N/A')
                    created_at_raw = rel.get('created_at', 'N/D')
                    created_at_display = created_at_raw.replace('T', ' ').replace('Z', '') if created_at_raw != 'N/D' else 'N/D'
                    assets_count = len(rel.get('assets', []))
                    
                    choice_str = f"{name} (Tag: {tag}, Data: {created_at_display}, Asset: {assets_count})"
                    release_choices.append(choice_str)
                    releases_map[choice_str] = rel
                
                if not release_choices:
                    self.output_text_ctrl.AppendText(_("Nessuna release valida trovata da modificare.\n"))
                    return

                # Dialogo di selezione release
                select_dlg = wx.SingleChoiceDialog(
                    self, 
                    _("Seleziona la release da modificare:"),
                    _("Modifica Release GitHub"), 
                    release_choices, 
                    wx.CHOICEDLG_STYLE
                )
                
                if select_dlg.ShowModal() != wx.ID_OK:
                    self.output_text_ctrl.AppendText(_("Modifica release annullata (selezione non effettuata).\n"))
                    select_dlg.Destroy()
                    return
                
                selected_choice_str = select_dlg.GetStringSelection()
                selected_release = releases_map.get(selected_choice_str)
                select_dlg.Destroy()

                if not selected_release:
                    self.output_text_ctrl.AppendText(_("Errore: selezione della release non valida.\n"))
                    return

                # Apri dialogo di modifica
                edit_dlg = EditReleaseDialog(self, _("Modifica Release GitHub"), selected_release)
                
                if edit_dlg.ShowModal() == wx.ID_OK:
                    values = edit_dlg.GetValues()
                    release_id = values["release_id"]
                    
                    # Prepara payload per aggiornare la release
                    update_payload = {
                        "name": values["release_name"],
                        "body": values["release_body"]
                    }
                    
                    # Aggiorna release via API
                    update_api_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/releases/{release_id}"
                    self.output_text_ctrl.AppendText(_("Aggiornamento release '{}' (ID: {})...\n").format(values["release_name"], release_id))
                    wx.Yield()
                    
                    try:
                        update_response = requests.patch(update_api_url, headers=headers, json=update_payload, timeout=15)
                        update_response.raise_for_status()
                        updated_release = update_response.json()
                        self.output_text_ctrl.AppendText(_("✅ Release aggiornata con successo!\n"))
                        self.output_text_ctrl.AppendText(_("🔗 URL: {}\n").format(updated_release.get('html_url')))
                        
                        # Elimina asset selezionati per l'eliminazione
                        assets_to_delete = values["assets_to_delete"]
                        if assets_to_delete:
                            self.output_text_ctrl.AppendText(_("🗑️ Eliminazione di {} asset...\n").format(len(assets_to_delete)))
                            successful_deletions = 0
                            
                            for asset_to_delete in assets_to_delete:
                                asset_id = asset_to_delete.get('id')
                                asset_name = asset_to_delete.get('name', 'N/A')
                                
                                if not asset_id:
                                    self.output_text_ctrl.AppendText(_("⚠️ ID asset mancante per '{}', salto eliminazione.\n").format(asset_name))
                                    continue
                                
                                delete_asset_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/releases/assets/{asset_id}"
                                self.output_text_ctrl.AppendText(_("🗑️ Eliminazione asset: '{}'...\n").format(asset_name))
                                wx.Yield()
                                
                                try:
                                    delete_response = requests.delete(delete_asset_url, headers=headers, timeout=30)
                                    delete_response.raise_for_status()
                                    
                                    self.output_text_ctrl.AppendText(_("✅ Asset '{}' eliminato con successo!\n").format(asset_name))
                                    successful_deletions += 1
                                    
                                except requests.exceptions.HTTPError as e_del:
                                    if e_del.response.status_code == 404:
                                        self.output_text_ctrl.AppendText(_("⚠️ Asset '{}' non trovato (già eliminato?)\n").format(asset_name))
                                    else:
                                        self.output_text_ctrl.AppendText(_("❌ Errore HTTP eliminazione asset '{}': {}\n").format(asset_name, e_del.response.status_code))
                                except requests.exceptions.RequestException as e_del_req:
                                    self.output_text_ctrl.AppendText(_("❌ Errore rete eliminazione asset '{}': {}\n").format(asset_name, e_del_req))
                                except Exception as e_del_gen:
                                    self.output_text_ctrl.AppendText(_("❌ Errore imprevisto eliminazione asset '{}': {}\n").format(asset_name, e_del_gen))
                            
                            self.output_text_ctrl.AppendText(_("📊 Asset eliminati con successo: {}/{}\n").format(successful_deletions, len(assets_to_delete)))
                        
                        # Upload nuovi asset se presenti
                        new_files = values["new_files_to_upload"]                        
                        if new_files:
                            upload_url_template = updated_release.get("upload_url", "")
                            if upload_url_template:
                                upload_url_base = upload_url_template.split("{")[0]
                                
                                self.output_text_ctrl.AppendText(_("Upload di {} nuovi asset...\n").format(len(new_files)))
                                successful_uploads = 0
                                
                                for fpath in new_files:
                                    filename = os.path.basename(fpath)
                                    params_upload = {"name": filename}
                                    self.output_text_ctrl.AppendText(_("📤 Upload: '{}'...\n").format(filename))
                                    wx.Yield()
                                    
                                    try:
                                        with open(fpath, "rb") as f:
                                            file_data = f.read()
                                        
                                        headers_asset_upload = headers.copy()
                                        headers_asset_upload["Content-Type"] = "application/octet-stream"
                                        
                                        response_asset = requests.post(
                                            upload_url_base, 
                                            headers=headers_asset_upload, 
                                            params=params_upload, 
                                            data=file_data, 
                                            timeout=120
                                        )
                                        response_asset.raise_for_status()
                                        asset_info = response_asset.json()
                                        
                                        self.output_text_ctrl.AppendText(_("✅ Asset '{}' caricato: {}\n").format(
                                            filename, asset_info.get('browser_download_url', 'N/A')
                                        ))
                                        successful_uploads += 1
                                        
                                    except requests.exceptions.RequestException as e_asset:
                                        self.output_text_ctrl.AppendText(_("❌ Errore upload asset '{}': {}\n").format(filename, e_asset))
                                    except IOError as e_io:
                                        self.output_text_ctrl.AppendText(_("❌ Errore lettura file '{}': {}\n").format(filename, e_io))
                                
                                self.output_text_ctrl.AppendText(_("📊 Asset caricati con successo: {}/{}\n").format(successful_uploads, len(new_files)))
                            else:
                                self.output_text_ctrl.AppendText(_("⚠️ Impossibile caricare nuovi asset: URL di upload non disponibile.\n"))
                        
                    except requests.exceptions.RequestException as e:
                        self.output_text_ctrl.AppendText(_("❌ Errore API GitHub (aggiornamento release): {}\n").format(e))
                        if hasattr(e, 'response') and e.response is not None:
                            self.output_text_ctrl.AppendText(_("Dettagli errore: {}\n").format(e.response.text[:500]))
                    except Exception as e_generic:
                        self.output_text_ctrl.AppendText(_("❌ Errore imprevisto durante aggiornamento release: {}\n").format(e_generic))
                else:
                    self.output_text_ctrl.AppendText(_("Modifica release annullata dall'utente.\n"))
                
                edit_dlg.Destroy()
                
            except requests.exceptions.RequestException as e_list:
                self.output_text_ctrl.AppendText(_("❌ Errore API GitHub (elenco release): {}\n").format(e_list))
                if hasattr(e_list, 'response') and e_list.response is not None:
                    self.output_text_ctrl.AppendText(_("Dettagli errore: {}\n").format(e_list.response.text[:500]))
            except Exception as e_generic_list:
                self.output_text_ctrl.AppendText(_("❌ Errore imprevisto durante elenco release: {}\n").format(e_generic_list))
            return
        elif command_name_key == CMD_GITHUB_LIST_ISSUES:
            self.handle_list_issues(command_name_key, command_details)
            return

        elif command_name_key == CMD_GITHUB_EDIT_ISSUE:
            self.handle_edit_issue(command_name_key, command_details)
            return

        elif command_name_key == CMD_GITHUB_DELETE_ISSUE:
            self.handle_delete_issue(command_name_key, command_details)
            return

        elif command_name_key == CMD_GITHUB_LIST_PRS:
            self.handle_list_prs(command_name_key, command_details)
            return

        elif command_name_key == CMD_GITHUB_EDIT_PR:
            self.handle_edit_pr(command_name_key, command_details)
            return

        elif command_name_key == CMD_GITHUB_DELETE_PR:
            self.handle_delete_pr(command_name_key, command_details)
            return
        elif command_name_key == CMD_GITHUB_CREATE_ISSUE:
            self.handle_create_issue(command_name_key, command_details)
            return

        elif command_name_key == CMD_GITHUB_CREATE_PR:
            self.handle_create_pull_request(command_name_key, command_details)
            return
        elif command_name_key == CMD_GITHUB_TRIGGER_WORKFLOW:
            self.output_text_ctrl.AppendText(_("Recupero lista workflow disponibili...\n"))
            wx.Yield()
            
            workflows = self.get_available_workflows()
            if not workflows:
                self.output_text_ctrl.AppendText(_("Nessun workflow attivo trovato nel repository {}/{}.\n").format(self.github_owner, self.github_repo))
                return
            
            workflow_choices = []
            workflow_map = {}
            for wf in workflows:
                choice_str = f"{wf['name']} ({wf['path']})"
                workflow_choices.append(choice_str)
                workflow_map[choice_str] = wf
            
            select_dlg = wx.SingleChoiceDialog(self, 
                                             _("Seleziona il workflow da avviare:"),
                                             _("Trigger Workflow per {}/{}").format(self.github_owner, self.github_repo),
                                             workflow_choices,
                                             wx.CHOICEDLG_STYLE)
            
            if select_dlg.ShowModal() != wx.ID_OK:
                self.output_text_ctrl.AppendText(_("Selezione workflow annullata.\n"))
                select_dlg.Destroy()
                return
            
            selected_choice = select_dlg.GetStringSelection()
            selected_workflow = workflow_map.get(selected_choice)
            select_dlg.Destroy()
            
            if not selected_workflow:
                self.output_text_ctrl.AppendText(_("Errore nella selezione del workflow.\n"))
                return
            
            input_dlg = WorkflowInputDialog(self, _("Trigger Workflow"), selected_workflow['name'])
            
            if input_dlg.ShowModal() != wx.ID_OK:
                self.output_text_ctrl.AppendText(_("Trigger workflow annullato.\n"))
                input_dlg.Destroy()
                return
            
            values = input_dlg.GetValues()
            input_dlg.Destroy()
            
            workflow_id = selected_workflow['id']
            trigger_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/actions/workflows/{workflow_id}/dispatches"
            
            payload = {
                'ref': values['branch'],
                'inputs': values['inputs']
            }
            
            self.output_text_ctrl.AppendText(
                _("🚀 Avvio workflow '{}' sul branch '{}' con {} input...\n").format(
                    selected_workflow['name'], values['branch'], len(values['inputs'])
                )
            )
            wx.Yield()
            
            try:
                response = requests.post(trigger_url, headers=headers, json=payload, timeout=15)
                response.raise_for_status()
                
                self.output_text_ctrl.AppendText(
                    _("✅ Workflow '{}' avviato con successo!\n").format(selected_workflow['name'])
                )
                self.output_text_ctrl.AppendText(
                    _("🔍 Usa '{}' per vedere le nuove esecuzioni.\n").format(CMD_GITHUB_LIST_WORKFLOW_RUNS)
                )
                
                suggest_msg = _("Vuoi monitorare automaticamente la nuova esecuzione quando sarà disponibile?")
                suggest_dlg = wx.MessageDialog(self, suggest_msg, _("Monitoraggio Automatico"), 
                                             wx.YES_NO | wx.ICON_QUESTION)
                suggest_response = suggest_dlg.ShowModal()
                suggest_dlg.Destroy()
                
                if suggest_response == wx.ID_YES or suggest_response == 2:
                    self.output_text_ctrl.AppendText(_("⏳ Attesa 5 secondi per la nuova esecuzione...\n"))
                    wx.CallLater(5000, self.auto_find_and_monitor_latest_run)
            
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 422:
                    self.output_text_ctrl.AppendText(_("❌ Errore 422: Il workflow potrebbe non supportare il dispatch manuale o i parametri sono incorretti.\n"))
                else:
                    self.output_text_ctrl.AppendText(_("❌ Errore HTTP {}: {}\n").format(e.response.status_code, e.response.text[:300]))
            except requests.exceptions.RequestException as e:
                self.output_text_ctrl.AppendText(_("❌ Errore di rete: {}\n").format(e))
            except Exception as e:
                self.output_text_ctrl.AppendText(_("❌ Errore imprevisto: {}\n").format(e))

        elif command_name_key == CMD_GITHUB_CANCEL_WORKFLOW:
            api_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/actions/runs"
            params = {'status': 'in_progress', 'per_page': 20}
            
            self.output_text_ctrl.AppendText(_("🔍 Ricerca workflow in esecuzione...\n"))
            wx.Yield()
            
            try:
                response = requests.get(api_url, headers=headers, params=params, timeout=15)
                response.raise_for_status()
                runs_data = response.json()
                
                running_runs = runs_data.get('workflow_runs', [])
                if not running_runs:
                    self.output_text_ctrl.AppendText(_("ℹ️ Nessun workflow attualmente in esecuzione nel repository {}/{}.\n").format(self.github_owner, self.github_repo))
                    return
                
                run_choices = []
                run_map = {}
                
                for run in running_runs:
                    status = run.get('status', 'unknown')
                    name = run.get('name', 'Workflow Sconosciuto')
                    created_at_raw = run.get('created_at', 'N/D')
                    
                    try:
                        if created_at_raw != 'N/D':
                            if created_at_raw.endswith('Z'):
                                utc_dt = datetime.fromisoformat(created_at_raw[:-1] + '+00:00')
                            else:
                                utc_dt = datetime.fromisoformat(created_at_raw).replace(tzinfo=timezone.utc)
                            local_dt = utc_dt.astimezone()
                            created_display = local_dt.strftime('%Y-%m-%d %H:%M:%S')
                        else:
                            created_display = 'N/D'
                    except:
                        created_display = created_at_raw.replace('T', ' ').replace('Z', '') if created_at_raw != 'N/D' else 'N/D'
                    
                    choice_str = f"🏃 {name} (ID: {run['id']}, Status: {status}, Avviato: {created_display})"
                    run_choices.append(choice_str)
                    run_map[choice_str] = run
                
                cancel_dlg = wx.SingleChoiceDialog(self,
                                                 _("Seleziona il workflow da cancellare:"),
                                                 _("Cancella Workflow in Esecuzione"),
                                                 run_choices,
                                                 wx.CHOICEDLG_STYLE)
                
                if cancel_dlg.ShowModal() != wx.ID_OK:
                    self.output_text_ctrl.AppendText(_("Cancellazione workflow annullata.\n"))
                    cancel_dlg.Destroy()
                    return
                
                selected_choice = cancel_dlg.GetStringSelection()
                selected_run = run_map.get(selected_choice)
                cancel_dlg.Destroy()
                
                if not selected_run:
                    self.output_text_ctrl.AppendText(_("Errore nella selezione del workflow.\n"))
                    return
                
                run_id = selected_run['id']
                run_name = selected_run.get('name', 'Sconosciuto')
                
                confirm_msg = _("⚠️ Sei sicuro di voler cancellare il workflow in esecuzione?\n\n"
                               "Nome: {}\n"
                               "ID: {}\n"
                               "Status: {}\n\n"
                               "Questa azione non può essere annullata.").format(
                    run_name, run_id, selected_run.get('status', 'unknown')
                )
                
                confirm_dlg = wx.MessageDialog(self, confirm_msg, _("Conferma Cancellazione"), 
                                             wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING)
                confirm_response = confirm_dlg.ShowModal()
                confirm_dlg.Destroy()
                
                if not (confirm_response == wx.ID_YES or confirm_response == 2):
                    self.output_text_ctrl.AppendText(_("Cancellazione workflow annullata dall'utente.\n"))
                    return
                
                cancel_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/actions/runs/{run_id}/cancel"
                
                self.output_text_ctrl.AppendText(_("🛑 Cancellazione workflow '{}' (ID: {})...\n").format(run_name, run_id))
                wx.Yield()
                
                cancel_response = requests.post(cancel_url, headers=headers, timeout=15)
                cancel_response.raise_for_status()
                
                self.output_text_ctrl.AppendText(_("✅ Workflow '{}' cancellato con successo!\n").format(run_name))
                self.output_text_ctrl.AppendText(_("ℹ️ Potrebbe essere necessario qualche secondo perché la cancellazione sia effettiva.\n"))
                
                verify_msg = _("Vuoi verificare lo stato del workflow tra qualche secondo?")
                verify_dlg = wx.MessageDialog(self, verify_msg, _("Verifica Stato"), wx.YES_NO | wx.ICON_QUESTION)
                verify_response = verify_dlg.ShowModal()
                verify_dlg.Destroy()
                
                if verify_response == wx.ID_YES or verify_response == 2:
                    wx.CallLater(3000, lambda: self.verify_workflow_cancellation(run_id, run_name))
            
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 409:
                    self.output_text_ctrl.AppendText(_("❌ Errore 409: Il workflow non può essere cancellato (potrebbe essere già terminato).\n"))
                else:
                    self.output_text_ctrl.AppendText(_("❌ Errore HTTP {}: {}\n").format(e.response.status_code, e.response.text[:300]))
            except requests.exceptions.RequestException as e:
                self.output_text_ctrl.AppendText(_("❌ Errore di rete: {}\n").format(e))
            except Exception as e:
                self.output_text_ctrl.AppendText(_("❌ Errore imprevisto: {}\n").format(e))

        elif command_name_key == CMD_GITHUB_DELETE_RELEASE:
            self.output_text_ctrl.AppendText(_("Recupero elenco release da GitHub per {}/{}\n").format(self.github_owner, self.github_repo))
            wx.Yield()
            releases_api_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/releases"
            try:
                response_list = requests.get(releases_api_url, headers=headers, params={"per_page": 50}, timeout=15)
                response_list.raise_for_status()
                releases_data = response_list.json()

                if not releases_data:
                    self.output_text_ctrl.AppendText(_("Nessuna release trovata per il repository {}/{}.\n").format(self.github_owner, self.github_repo))
                    return

                release_choices = []
                self.releases_map_for_delete = {} 
                for rel in releases_data:
                    name = rel.get('name', _('Senza nome'))
                    tag = rel.get('tag_name', 'N/A')
                    created_at_raw = rel.get('created_at', 'N/D')
                    created_at_display = created_at_raw.replace('T', ' ').replace('Z', '') if created_at_raw != 'N/D' else 'N/D'
                    choice_str = f"{name} (Tag: {tag}, Data: {created_at_display}, ID: {rel['id']})"
                    release_choices.append(choice_str)
                    self.releases_map_for_delete[choice_str] = rel
                
                if not release_choices:
                    self.output_text_ctrl.AppendText(_("Nessuna release valida trovata da elencare per l'eliminazione.\n"))
                    return

                dlg_select_release = wx.SingleChoiceDialog(self, 
                                _("Seleziona la release da eliminare:"),
                                _("Elimina Release GitHub"), 
                                release_choices, 
                                wx.CHOICEDLG_STYLE | wx.OK | wx.CANCEL)
                
                selected_release_obj = None
                selected_display_name_for_confirm = "N/D"

                if dlg_select_release.ShowModal() == wx.ID_OK:
                    selected_choice_str = dlg_select_release.GetStringSelection()
                    selected_release_obj = self.releases_map_for_delete.get(selected_choice_str)
                    if selected_release_obj:
                        rel_name_confirm = selected_release_obj.get('name', '')
                        rel_tag_confirm = selected_release_obj.get('tag_name', '')
                        if rel_name_confirm and rel_tag_confirm:
                            selected_display_name_for_confirm = f"{rel_name_confirm} (Tag: {rel_tag_confirm})"
                        elif rel_name_confirm:
                            selected_display_name_for_confirm = rel_name_confirm
                        elif rel_tag_confirm:
                            selected_display_name_for_confirm = f"Release con Tag: {rel_tag_confirm}"
                        else:
                            selected_display_name_for_confirm = f"Release ID: {selected_release_obj['id']}"
                    else:
                        self.output_text_ctrl.AppendText(_("Errore: selezione della release non valida.\n"))
                        dlg_select_release.Destroy()
                        return
                else:
                    self.output_text_ctrl.AppendText(_("Eliminazione release annullata (selezione non effettuata).\n"))
                    dlg_select_release.Destroy()
                    return
                dlg_select_release.Destroy()

                if not selected_release_obj:
                    self.output_text_ctrl.AppendText(_("Errore interno: oggetto release selezionato non trovato.\n"))
                    return

                release_id_to_delete = selected_release_obj['id']
                target_tag_name = selected_release_obj.get('tag_name')

                confirm_msg_template = command_details.get("confirm_template", _("Sei sicuro di voler eliminare la release '{release_display_name}'?"))
                confirm_msg_filled = confirm_msg_template.replace("{release_display_name}", selected_display_name_for_confirm)
                
                confirm_dialog = wx.MessageDialog(self, confirm_msg_filled, _("Conferma Eliminazione Release"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING)
                response_confirm_delete = confirm_dialog.ShowModal()
                print(f"DEBUG_DELETE_RELEASE_CONFIRM: Dialogo conferma eliminazione release ha restituito: {response_confirm_delete}, wx.ID_YES è {wx.ID_YES}")
                confirm_dialog.Destroy()

                if not (response_confirm_delete == wx.ID_YES or response_confirm_delete == 2):
                    self.output_text_ctrl.AppendText(_("Eliminazione della release '{}' annullata dall'utente.\n").format(selected_display_name_for_confirm))
                    return
                
                self.output_text_ctrl.AppendText(_("Tentativo di eliminare la release: '{}' (ID: {}) dal repository {}/{}\n").format(selected_display_name_for_confirm, release_id_to_delete, self.github_owner, self.github_repo))
                wx.Yield()
                
                delete_api_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/releases/{release_id_to_delete}"
                self.output_text_ctrl.AppendText(_("Invio richiesta DELETE a: {}\n").format(delete_api_url))
                wx.Yield()
                try:
                    delete_response = requests.delete(delete_api_url, headers=headers, timeout=15)
                    delete_response.raise_for_status() 
                    self.output_text_ctrl.AppendText(_("Release '{}' (ID: {}) eliminata con successo da GitHub.\n").format(selected_display_name_for_confirm, release_id_to_delete))

                    if target_tag_name:
                        confirm_delete_tag_msg = _("La release è stata eliminata da GitHub.\nVuoi tentare di eliminare anche il tag Git '{tag}' dal repository remoto 'origin'?\n(Comando: git push origin --delete {tag})").format(tag=target_tag_name)
                        tag_delete_dialog = wx.MessageDialog(self, confirm_delete_tag_msg, _("Elimina Tag Git Remoto?"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
                        response_delete_tag = tag_delete_dialog.ShowModal()
                        print(f"DEBUG_DELETE_TAG_CONFIRM: Dialogo conferma eliminazione tag ha restituito: {response_delete_tag}, wx.ID_YES è {wx.ID_YES}")
                        tag_delete_dialog.Destroy()

                        if response_delete_tag == wx.ID_YES or response_delete_tag == 2:
                            self.output_text_ctrl.AppendText(_("\nTentativo di eliminare il tag Git remoto '{}'...\n").format(target_tag_name))
                            wx.Yield()
                            repo_path = self.repo_path_ctrl.GetValue()
                            if self.RunSingleGitCommand(["git", "push", "origin", "--delete", target_tag_name], repo_path, _("Elimina tag remoto {}").format(target_tag_name)):
                                 self.output_text_ctrl.AppendText(_("Comando per eliminare il tag remoto '{}' eseguito. Controlla l'output per il successo effettivo.\n").format(target_tag_name))
                            else:
                                 self.output_text_ctrl.AppendText(_("Comando per eliminare il tag remoto '{}' fallito o con errori. Controlla l'output sopra.\n").format(target_tag_name))
                        else:
                            self.output_text_ctrl.AppendText(_("\nIl tag Git remoto '{}' non è stato eliminato.\n").format(target_tag_name))
                except requests.exceptions.HTTPError as e_del:
                    if e_del.response.status_code == 404:
                        self.output_text_ctrl.AppendText(_("ERRORE: Release ID {} (selezionata: '{}') non trovata.\n").format(release_id_to_delete, selected_display_name_for_confirm))
                    else:
                        self.output_text_ctrl.AppendText(_("ERRORE API GitHub (eliminazione release ID {}): {}\n").format(release_id_to_delete, e_del))
                        if hasattr(e_del, 'response') and e_del.response is not None:
                            self.output_text_ctrl.AppendText(_("Dettagli errore API: {}\n").format(e_del.response.text[:500]))
                except requests.exceptions.RequestException as e_del:
                    self.output_text_ctrl.AppendText(_("ERRORE API GitHub (eliminazione release ID {}): {}\n").format(release_id_to_delete, e_del))
                except Exception as e_generic:
                    self.output_text_ctrl.AppendText(_("ERRORE imprevisto durante l'eliminazione della release: {}\n").format(e_generic))
            except requests.exceptions.RequestException as e_list:
                self.output_text_ctrl.AppendText(_("ERRORE API GitHub (elenco release): {}\n").format(e_list))
                if hasattr(e_list, 'response') and e_list.response is not None:
                    self.output_text_ctrl.AppendText(_("Dettagli errore API: {}\n").format(e_list.response.text[:500]))
            except Exception as e_generic_list:
                self.output_text_ctrl.AppendText(_("ERRORE imprevisto durante l'elenco delle release: {}\n").format(e_generic_list))
            return

        if command_name_key == CMD_GITHUB_SELECTED_RUN_LOGS:
            self.output_text_ctrl.AppendText(f"DEBUG: Comando ricevuto = '{command_name_key}'\n")

            # MODIFICA: Permettere all'utente di scegliere quale run visualizzare
            
            # Prima otteniamo la lista delle run disponibili
            api_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/actions/runs"
            params = {'per_page': 30}  # Aumentiamo il numero per più opzioni
            branches_to_try = ['main', 'master']
            all_runs_from_branches = []
            
            self.output_text_ctrl.AppendText(_("Recupero lista esecuzioni workflow per selezionare quale visualizzare...\n"))
            wx.Yield()
            
            for branch_name in branches_to_try:
                params['branch'] = branch_name
                try:
                    response = requests.get(api_url, headers=headers, params=params, timeout=15)
                    response.raise_for_status()
                    runs_data = response.json()
                    branch_runs = runs_data.get('workflow_runs', [])
                    if branch_runs:
                        all_runs_from_branches.extend(branch_runs)
                except requests.exceptions.RequestException as e:
                    self.output_text_ctrl.AppendText(_("Errore nel recuperare esecuzioni per branch {}: {}\n").format(branch_name, e))
            
            if not all_runs_from_branches:
                self.output_text_ctrl.AppendText(_("Nessuna esecuzione workflow trovata per visualizzare i log.\n"))
                return
            
            # Rimuovi duplicati e ordina per data
            unique_runs_dict = {run['id']: run for run in all_runs_from_branches}
            unique_runs_list = sorted(list(unique_runs_dict.values()), key=lambda r: r.get('created_at', ''), reverse=True)
            
            # Prepara le opzioni per la selezione
            run_choices = []
            runs_map_for_logs = {}
            
            for run in unique_runs_list[:50]:  # Limita a 50 per performance
                status_val = run.get('status', _('sconosciuto'))
                conclusion_val = run.get('conclusion', _('in corso')) if status_val != 'completed' else run.get('conclusion', _('N/D'))
                created_at_raw = run.get('created_at', 'N/D')
                
                # Formatta la data
                try:
                    if created_at_raw != 'N/D':
                        if created_at_raw.endswith('Z'):
                            utc_dt = datetime.fromisoformat(created_at_raw[:-1] + '+00:00')
                        else:
                            utc_dt = datetime.fromisoformat(created_at_raw).replace(tzinfo=timezone.utc)
                        local_dt = utc_dt.astimezone()
                        created_at_display = local_dt.strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        created_at_display = 'N/D'
                except:
                    created_at_display = created_at_raw.replace('T', ' ').replace('Z', '') if created_at_raw != 'N/D' else 'N/D'
                
                # Aggiungi indicatore se è la run attualmente selezionata
                current_indicator = " ⭐ [ATTUALMENTE SELEZIONATA]" if run['id'] == self.selected_run_id else ""
                
                choice_str = f"ID: {run['id']} - {run.get('name', _('Workflow Sconosciuto'))} ({conclusion_val}, {status_val}) - {created_at_display}{current_indicator}"
                run_choices.append(choice_str)
                runs_map_for_logs[choice_str] = run
            
            if not run_choices:
                self.output_text_ctrl.AppendText(_("Nessuna esecuzione di workflow trovata da cui recuperare i log.\n"))
                return
            
            # Dialog per selezione della run di cui visualizzare i log
            dlg = wx.SingleChoiceDialog(
                self, 
                _("Seleziona l'esecuzione di cui vuoi visualizzare i log:"),
                _("Visualizza Log Workflow per {}/{}").format(self.github_owner, self.github_repo),
                run_choices, 
                wx.CHOICEDLG_STYLE | wx.OK | wx.CANCEL
            )
            
            if dlg.ShowModal() != wx.ID_OK:
                self.output_text_ctrl.AppendText(_("Visualizzazione log annullata.\n"))
                dlg.Destroy()
                return
            
            selected_choice_str = dlg.GetStringSelection()
            selected_run_for_logs = runs_map_for_logs.get(selected_choice_str)
            dlg.Destroy()
            
            if not selected_run_for_logs:
                self.output_text_ctrl.AppendText(_("Errore nella selezione dell'esecuzione per i log.\n"))
                return
            
            # Usa la run selezionata per i log (non necessariamente quella salvata in self.selected_run_id)
            run_id_for_logs = selected_run_for_logs['id']
            workflow_name_for_logs = selected_run_for_logs.get('name', _('Workflow Sconosciuto'))
            
            self.output_text_ctrl.AppendText(_("Recupero log per: '{}' (ID: {})\n").format(workflow_name_for_logs, run_id_for_logs))
            
            # Verifica stato della run selezionata
            run_status_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/actions/runs/{run_id_for_logs}"
            self.output_text_ctrl.AppendText(_("Verifica stato esecuzione ID {}...\n").format(run_id_for_logs))
            wx.Yield()
            
            current_status_from_api = "unknown"
            allow_log_download_attempt = False

            try:
                run_resp = requests.get(run_status_url, headers=headers, timeout=10)
                run_resp.raise_for_status()
                run_data = run_resp.json()
                current_status_from_api = run_data.get('status', 'unknown').lower()
                current_conclusion_from_api = run_data.get('conclusion')
                workflow_run_display_name = run_data.get('name', _('(Nome Run Sconosciuto)'))

                self.output_text_ctrl.AppendText(_("Stato attuale API: {}, Conclusione API: {}\n").format(
                    current_status_from_api, current_conclusion_from_api if current_conclusion_from_api is not None else _("Non ancora disponibile/definitiva")
                ))
                
                non_completed_states = ['queued', 'in_progress', 'waiting', 'requested', 'pending', 'action_required', 'stale']

                if current_status_from_api in non_completed_states:
                    dlg_msg = _("L'esecuzione del workflow ID {} è ancora '{}'.\n"
                                "I log potrebbero essere incompleti o non disponibili finché non sarà completata.\n\n"
                                "Vuoi procedere comunque con il download dei log disponibili?").format(run_id_for_logs, current_status_from_api)
                    
                    proceed_dialog = wx.MessageDialog(self, dlg_msg, _("Esecuzione in Corso"),
                                                      wx.YES_NO | wx.ICON_QUESTION)
                    response = proceed_dialog.ShowModal()
                    proceed_dialog.Destroy()

                    if response == wx.ID_YES or response == 2:
                        self.output_text_ctrl.AppendText(_("Procedendo con il download dei log parziali per run ID {}.\n").format(run_id_for_logs))
                        allow_log_download_attempt = True
                    else: 
                        self.output_text_ctrl.AppendText(_("Download log annullato per run in corso.\n"))
                        return
                
                elif current_status_from_api == 'completed':
                    allow_log_download_attempt = True
                    if current_conclusion_from_api is None:
                         self.output_text_ctrl.AppendText(_("AVVISO: L'esecuzione è completata ma la conclusione API non è definita. I log potrebbero essere disponibili.\n"))
                
                else:
                    self.output_text_ctrl.AppendText(_("AVVISO: Stato esecuzione '{}'. Il download dei log potrebbe non riuscire o i log potrebbero riflettere questo stato.\n").format(current_status_from_api))
                    allow_log_download_attempt = True

            except requests.exceptions.RequestException as e_stat:
                self.output_text_ctrl.AppendText(_("Errore durante la verifica dello stato aggiornato dell'esecuzione: {}. Procedo comunque al tentativo di download log.\n").format(e_stat))
                allow_log_download_attempt = True 
            
            if not allow_log_download_attempt:
                 self.output_text_ctrl.AppendText(_("Download dei log non tentato a causa dello stato dell'esecuzione o della scelta dell'utente.\n"))
                 return
            
            # Download dei log per la run selezionata
            logs_zip_url_api = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/actions/runs/{run_id_for_logs}/logs"
            self.output_text_ctrl.AppendText(_("Download dei log per l'esecuzione ID {} (repo {}/{})...\n").format(run_id_for_logs, self.github_owner, self.github_repo))
            wx.Yield()
            
            try:
                response = requests.get(logs_zip_url_api, headers=headers, stream=True, allow_redirects=True, timeout=30)
                response.raise_for_status()
                if 'application/zip' not in response.headers.get('Content-Type', '').lower():
                    self.output_text_ctrl.AppendText(_("Errore: La risposta non è un file ZIP. Content-Type: {}\n").format(response.headers.get('Content-Type')))
                    try:
                        api_response_json = response.json()
                        if api_response_json and 'message' in api_response_json:
                             self.output_text_ctrl.AppendText(_("Messaggio API: {}\n").format(api_response_json['message']))
                    except json.JSONDecodeError:
                        self.output_text_ctrl.AppendText(_("Risposta API non JSON: {}\n").format(response.text[:200]))
                    return
                
                self.output_text_ctrl.AppendText(_("Archivio ZIP dei log scaricato. Estrazione in corso...\n"))
                wx.Yield()
                log_content_found = False
                with io.BytesIO(response.content) as zip_in_memory, zipfile.ZipFile(zip_in_memory, 'r') as zip_ref:
                    file_list = zip_ref.namelist()
                    self.output_text_ctrl.AppendText(_("File nell'archivio ZIP:\n") + "\n".join(f"  - {f}" for f in file_list) + "\n\n")
                    
                    # Logica per selezionare quale file di log visualizzare
                    log_files = [f for f in file_list if f.endswith('.txt')]
                    
                    if not log_files:
                        self.output_text_ctrl.AppendText(_("Nessun file di log (.txt) trovato nell'archivio.\n"))
                        return
                    
                    log_file_to_display = None
                    
                    # Se ci sono più file di log, permetti all'utente di scegliere
                    if len(log_files) > 1:
                        log_choices = []
                        for log_file in log_files:
                            try:
                                # Prova a ottenere info sul file per aiutare nella scelta
                                file_info = zip_ref.getinfo(log_file)
                                size_kb = file_info.file_size // 1024
                                choice_str = f"{log_file} ({size_kb} KB)"
                            except:
                                choice_str = log_file
                            log_choices.append(choice_str)
                        
                        log_dlg = wx.SingleChoiceDialog(
                            self,
                            _("Trovati {} file di log. Seleziona quale visualizzare:").format(len(log_files)),
                            _("Selezione File di Log"),
                            log_choices,
                            wx.CHOICEDLG_STYLE
                        )
                        
                        if log_dlg.ShowModal() == wx.ID_OK:
                            selected_log_index = log_dlg.GetSelection()
                            log_file_to_display = log_files[selected_log_index]
                        else:
                            self.output_text_ctrl.AppendText(_("Selezione file di log annullata.\n"))
                            log_dlg.Destroy()
                            return
                        log_dlg.Destroy()
                    else:
                        log_file_to_display = log_files[0]
                    
                    if log_file_to_display:
                        self.output_text_ctrl.AppendText(_("--- Contenuto di: {} ---\n").format(log_file_to_display))
                        try:
                            log_data_bytes = zip_ref.read(log_file_to_display)
                            log_data = log_data_bytes.decode('utf-8', errors='replace')

                            # Applica le preferenze di visualizzazione timestamp
                            if not self.github_strip_log_timestamps:
                                log_data = re.sub(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:?\d{2})?)',
                                                  self.convert_utc_to_local_timestamp_match, log_data, flags=re.MULTILINE)
                            elif self.github_strip_log_timestamps:
                                log_data = re.sub(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?\s*', '', log_data, flags=re.MULTILINE)
                                log_data = re.sub(r'^\[[^\]]+\]\s*\[\d{2}:\d{2}:\d{2}(?:\.\d+)?\]\s*', '', log_data, flags=re.MULTILINE)

                            self.output_text_ctrl.AppendText(log_data)
                            log_content_found = True
                        except Exception as e_decode:
                            self.output_text_ctrl.AppendText(_("Errore nella decodifica o elaborazione del file di log {}: {}\n").format(log_file_to_display, e_decode))
                    else:
                        self.output_text_ctrl.AppendText(_("Nessun file di log selezionato per la visualizzazione.\n"))
                
                if log_content_found:
                    self.output_text_ctrl.AppendText(_("\n--- Fine dei log ---\n"))
                    # Opzione per aggiornare la run selezionata
                    if run_id_for_logs != self.selected_run_id:
                        update_msg = _("Vuoi impostare questa esecuzione (ID: {}) come quella attualmente selezionata per future operazioni?").format(run_id_for_logs)
                        update_dlg = wx.MessageDialog(self, update_msg, _("Aggiorna Run Selezionata"), wx.YES_NO | wx.ICON_QUESTION)
                        if update_dlg.ShowModal() == wx.ID_YES:
                            self.selected_run_id = run_id_for_logs
                            self.output_text_ctrl.AppendText(_("✅ Run selezionata aggiornata a ID: {}\n").format(run_id_for_logs))
                        update_dlg.Destroy()
                else:
                    self.output_text_ctrl.AppendText(_("\nNessun contenuto di log visualizzato.\n"))
            
            except requests.exceptions.HTTPError as e: 
                self.output_text_ctrl.AppendText(_("Errore HTTP API GitHub: {} - {}\n").format(e.response.status_code, e.response.text[:500]))
                if e.response.status_code == 404:
                    self.output_text_ctrl.AppendText(_("Possibile causa: L'esecuzione workflow o i log potrebbero essere scaduti o l'ID non è valido.\n"))
                elif e.response.status_code == 410:
                    self.output_text_ctrl.AppendText(_("Errore 410: I log per questa esecuzione sono scaduti e non più disponibili.\n"))
            except requests.exceptions.RequestException as e:
                self.output_text_ctrl.AppendText(_("Errore API GitHub: {}\n").format(e))
            except zipfile.BadZipFile:
                self.output_text_ctrl.AppendText(_("Errore: Il file scaricato non è un archivio ZIP valido.\n"))
            except Exception as e_generic:
                self.output_text_ctrl.AppendText(_("Errore imprevisto durante il recupero dei log: {}\n").format(e_generic))
            
            return
        elif command_name_key == CMD_GITHUB_DOWNLOAD_SELECTED_ARTIFACT:
            if not self.selected_run_id:
                self.output_text_ctrl.AppendText(_("Errore: ID esecuzione non selezionato. Esegui prima '{}'.\n").format(CMD_GITHUB_LIST_WORKFLOW_RUNS))
                return
            
            run_status_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/actions/runs/{self.selected_run_id}"
            self.output_text_ctrl.AppendText(_("Verifica stato attuale esecuzione ID {} (per artefatti)...\n").format(self.selected_run_id))
            wx.Yield()
            current_status_from_api = "unknown"
            allow_artifact_attempt = False
            try:
                run_resp = requests.get(run_status_url, headers=headers, timeout=10)
                run_resp.raise_for_status()
                run_data = run_resp.json()
                current_status_from_api = run_data.get('status', 'unknown')
                current_conclusion_from_api = run_data.get('conclusion')
                self.output_text_ctrl.AppendText(_("Stato attuale API (artefatti): {}, Conclusione API: {}\n").format(current_status_from_api, current_conclusion_from_api if current_conclusion_from_api is not None else _("Non ancora disponibile/definitiva")))
                if current_status_from_api.lower() == 'completed':
                    allow_artifact_attempt = True
                    if current_conclusion_from_api is None:
                        self.output_text_ctrl.AppendText(_("AVVISO: Esecuzione completata ma conclusione API non definita.\n"))
                elif current_status_from_api.lower() in ['queued', 'in_progress', 'requested', 'waiting', 'pending', 'action_required', 'stale']:
                    self.output_text_ctrl.AppendText(_("AVVISO: Esecuzione '{}'. Artefatti potrebbero non essere ancora disponibili o completi.\n").format(current_status_from_api))
                    allow_artifact_attempt = True
                else:
                    self.output_text_ctrl.AppendText(_("AVVISO: Stato esecuzione '{}'.\n").format(current_status_from_api))
                    allow_artifact_attempt = True
            except requests.exceptions.RequestException as e_stat:
                self.output_text_ctrl.AppendText(_("Errore verifica stato esecuzione (artefatti): {}. Procedo.\n").format(e_stat))
                allow_artifact_attempt = True
            
            if not allow_artifact_attempt:
                self.output_text_ctrl.AppendText(_("Recupero artefatti interrotto.\n"))
                return

            artifacts_api_url = f"https://api.github.com/repos/{self.github_owner}/{self.github_repo}/actions/runs/{self.selected_run_id}/artifacts"
            self.output_text_ctrl.AppendText(_("Recupero lista artefatti per esecuzione ID {}...\n").format(self.selected_run_id))
            wx.Yield()
            try:
                response = requests.get(artifacts_api_url, headers=headers, timeout=10)
                response.raise_for_status()
                artifacts_data = response.json()
                if artifacts_data.get('total_count', 0) == 0 or not artifacts_data.get('artifacts'):
                    self.output_text_ctrl.AppendText(_("Nessun artefatto trovato.\n"))
                    return
                
                artifact_choices = []
                artifact_map = {}
                for art in artifacts_data['artifacts']:
                    expires_at_str = art.get('expires_at', 'N/D')
                    try:
                        expires_at_display = expires_at_str[:10] if expires_at_str and expires_at_str != 'N/D' else _('N/D')
                    except:
                        expires_at_display = _('N/D') 
                    size_kb = art.get('size_in_bytes', 0) // 1024
                    choice_str = f"{art['name']} ({size_kb} KB, Scade: {expires_at_display})"
                    artifact_choices.append(choice_str)
                    artifact_map[choice_str] = art
                
                if not artifact_choices:
                    self.output_text_ctrl.AppendText(_("Nessun artefatto valido da elencare.\n"))
                    return
                
                choice_dlg = wx.SingleChoiceDialog(self, _("Seleziona un artefatto da scaricare:"), _("Download Artefatto per {}/{}").format(self.github_owner, self.github_repo), artifact_choices, wx.CHOICEDLG_STYLE)
                if choice_dlg.ShowModal() == wx.ID_OK:
                    selected_choice_str = choice_dlg.GetStringSelection()
                    selected_artifact = artifact_map.get(selected_choice_str)
                    if selected_artifact:
                        artifact_name_from_api = selected_artifact['name']
                        default_file_name = f"{artifact_name_from_api}.zip"
                        download_url = selected_artifact['archive_download_url']
                        save_dialog = wx.FileDialog(self, _("Salva Artefatto Come..."), defaultDir=os.getcwd(), defaultFile=default_file_name, wildcard=_("File ZIP (*.zip)|*.zip|Tutti i file (*.*)|*.*"), style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
                        if save_dialog.ShowModal() == wx.ID_OK:
                            save_path = save_dialog.GetPath()
                            self.output_text_ctrl.AppendText(_("Download di '{}' in corso...\nA: {}\n").format(default_file_name, save_path))
                            wx.Yield()
                            try:
                                artifact_response = requests.get(download_url, headers=headers, stream=True, allow_redirects=True, timeout=120)
                                artifact_response.raise_for_status()
                                with open(save_path, 'wb') as f:
                                    for chunk in artifact_response.iter_content(chunk_size=8192):
                                        f.write(chunk)
                                self.output_text_ctrl.AppendText(_("Artefatto '{}' scaricato: {}\n").format(default_file_name, save_path))
                            except requests.exceptions.RequestException as e_dl:
                                self.output_text_ctrl.AppendText(_("Errore download artefatto: {}\n").format(e_dl))
                            except IOError as e_io:
                                self.output_text_ctrl.AppendText(_("Errore salvataggio artefatto: {}\n").format(e_io))
                        else:
                            self.output_text_ctrl.AppendText(_("Salvataggio artefatto annullato.\n"))
                        save_dialog.Destroy()
                else:
                    self.output_text_ctrl.AppendText(_("Selezione artefatto annullata.\n"))
                choice_dlg.Destroy()
            except requests.exceptions.HTTPError as e:
                self.output_text_ctrl.AppendText(_("Errore HTTP API GitHub: {} - {}\n").format(e.response.status_code, e.response.text[:500]))
                if e.response.status_code == 404:
                    self.output_text_ctrl.AppendText(_("Causa: Esecuzione/artefatti scaduti o ID non valido.\n"))
                elif e.response.status_code == 410:
                    self.output_text_ctrl.AppendText(_("Errore 410: Artefatti scaduti.\n"))
            except requests.exceptions.RequestException as e:
                self.output_text_ctrl.AppendText(_("Errore API GitHub: {}\n").format(e))
            except Exception as e_generic:
                self.output_text_ctrl.AppendText(_("Errore imprevisto recupero artefatti: {}\n").format(e_generic))

    def RunSingleGitCommand(self, cmd_parts, repo_path, operation_description="Comando Git"):
        process_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        output = ""
        success = False
        try:
            proc = subprocess.run(cmd_parts, cwd=repo_path, capture_output=True, text=True, check=False, encoding='utf-8', errors='replace', creationflags=process_flags)
            if proc.stdout: output += _("--- Output ({}): ---\n{}\n").format(operation_description, proc.stdout)
            if proc.stderr: output += _("--- Messaggi/Errori ({}): ---\n{}\n").format(operation_description, proc.stderr)
            if proc.returncode == 0:
                success = True
            else:
                output += _("\n!!! Operazione '{}' fallita con codice di uscita: {} !!!\n").format(operation_description, proc.returncode)
        except Exception as e:
            output += _("Errore durante l'operazione '{}': {}\n").format(operation_description, str(e))
        self.output_text_ctrl.AppendText(output)
        return success

    def GetCurrentBranchName(self, repo_path):
        process_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        try:
            proc = subprocess.run(["git", "branch", "--show-current"], cwd=repo_path,
                                    capture_output=True, text=True, check=True,
                                    encoding='utf-8', errors='replace', creationflags=process_flags)
            return proc.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError, Exception):
            return None

    def HandlePushNoUpstream(self, repo_path, original_stderr):
        self.output_text_ctrl.AppendText(
            _("\n*** PROBLEMA PUSH: Il branch corrente non ha un upstream remoto configurato. ***\n"
              "Questo di solito accade la prima volta che si tenta di inviare (push) un nuovo branch locale al server remoto.\n")
        )
        current_branch = self.GetCurrentBranchName(repo_path)
        parsed_branch_from_error = None
        if not current_branch: # Prova a dedurlo dall'errore se GetCurrentBranchName fallisce
            match_fatal = re.search(r"fatal: The current branch (\S+) has no upstream branch", original_stderr, re.IGNORECASE)
            if match_fatal: parsed_branch_from_error = match_fatal.group(1)
            else: # Cerca il suggerimento di Git
                match_hint = re.search(r"git push --set-upstream origin\s+(\S+)", original_stderr, re.IGNORECASE)
                if match_hint: parsed_branch_from_error = match_hint.group(1).splitlines()[0].strip() # Prendi solo il nome del branch
            if parsed_branch_from_error:
                current_branch = parsed_branch_from_error
                self.output_text_ctrl.AppendText(_("Branch corrente rilevato dall'errore Git: '{}'\n").format(current_branch))

        if not current_branch:
            self.output_text_ctrl.AppendText(_("Impossibile determinare automaticamente il nome del branch corrente.\n"
                                 "Dovrai eseguire manualmente il comando: git push --set-upstream origin <nome-del-tuo-branch>\n"))
            return
        suggestion_command_str = f"git push --set-upstream origin {current_branch}"
        confirm_msg = (_("Il branch locale '{}' non sembra essere collegato a un branch remoto (upstream) su 'origin'.\n\n"
                       "Vuoi eseguire il seguente comando per impostare il tracciamento e inviare le modifiche?\n\n"
                       "    {}\n\n"
                       "Questo collegherà il branch locale '{}' al branch remoto 'origin/{}'.").format(current_branch, suggestion_command_str, current_branch, current_branch))
        dlg = wx.MessageDialog(self, confirm_msg, _("Impostare Upstream e Fare Push?"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
        response = dlg.ShowModal()
        dlg.Destroy()
        if response == wx.ID_YES:
            self.output_text_ctrl.AppendText(_("\nEsecuzione di: {}...\n").format(suggestion_command_str)); wx.Yield()
            command_parts = ["git", "push", "--set-upstream", "origin", current_branch]
            if self.RunSingleGitCommand(command_parts, repo_path, _("Push con impostazione upstream per '{}'").format(current_branch)):
                self.output_text_ctrl.AppendText(_("\nPush con --set-upstream per '{}' completato con successo.\n").format(current_branch))
            else:
                self.output_text_ctrl.AppendText(_("\nTentativo di push con --set-upstream per '{}' fallito. Controlla l'output sopra per i dettagli.\n").format(current_branch))
        else:
            self.output_text_ctrl.AppendText(_("\nOperazione annullata dall'utente. Il branch non è stato inviato né collegato al remoto.\n"
                                 "Se necessario, puoi eseguire manualmente il comando: {}\n").format(suggestion_command_str))

    def HandleBranchNotMerged(self, repo_path, branch_name):
        confirm_force_delete_msg = (_("Il branch '{}' non è completamente unito (not fully merged).\n"
                                    "Se elimini questo branch forzatamente (usando l'opzione -D), i commit unici su di esso andranno persi.\n\n"
                                    "Vuoi forzare l'eliminazione del branch locale (git branch -D {})?").format(branch_name, branch_name))
        dlg = wx.MessageDialog(self, confirm_force_delete_msg, _("Forzare Eliminazione Branch Locale?"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING)
        response = dlg.ShowModal()
        dlg.Destroy()
        if response == wx.ID_YES:
            self.output_text_ctrl.AppendText(_("\nTentativo di forzare l'eliminazione del branch locale '{}'...\n").format(branch_name)); wx.Yield()
            if self.RunSingleGitCommand(["git", "branch", "-D", branch_name], repo_path, _("Forza eliminazione branch locale {}").format(branch_name)):
                self.output_text_ctrl.AppendText(_("Branch locale '{}' eliminato forzatamente.\n").format(branch_name))
            else: self.output_text_ctrl.AppendText(_("Eliminazione forzata del branch locale '{}' fallita. Controlla l'output.\n").format(branch_name))
        else: self.output_text_ctrl.AppendText(_("\nEliminazione forzata del branch locale non eseguita.\n"))

    def HandleMergeConflict(self, repo_path):
        self.output_text_ctrl.AppendText(_("\n*** CONFLITTI DI MERGE RILEVATI! ***\n"))
        process_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        conflicting_files_list = []
        try:
            # Prova prima con 'git status --porcelain' che è più affidabile per 'UU'
            status_proc = subprocess.run(["git", "status", "--porcelain"], cwd=repo_path, capture_output=True, text=True, check=True, encoding='utf-8', errors='replace', creationflags=process_flags)
            conflicting_files_list = [line.split()[-1] for line in status_proc.stdout.strip().splitlines() if line.startswith("UU ")]
            if conflicting_files_list:
                self.output_text_ctrl.AppendText(_("File con conflitti (marcati come UU in 'git status'):\n{}\n\n").format("\n".join(conflicting_files_list)))
            else: # Fallback se 'UU' non viene trovato, prova con diff --diff-filter=U
                diff_proc = subprocess.run(["git", "diff", "--name-only", "--diff-filter=U"], cwd=repo_path, capture_output=True, text=True, check=True, encoding='utf-8', errors='replace', creationflags=process_flags)
                conflicting_files_list = diff_proc.stdout.strip().splitlines()
                if conflicting_files_list: self.output_text_ctrl.AppendText(_("File con conflitti (rilevati da diff --diff-filter=U):\n{}\n\n").format("\n".join(conflicting_files_list)))
                else: self.output_text_ctrl.AppendText(_("Merge fallito, ma nessun file in conflitto specifico rilevato automaticamente dai comandi standard. Controlla 'git status' manualmente.\n"))

            dialog_message = (_("Il merge è fallito a causa di conflitti.\n\n"
                              "Spiegazione delle opzioni di risoluzione automatica:\n"
                              " - 'Usa versione del BRANCH CORRENTE (--ours)': Per ogni file in conflitto, mantiene la versione del branch su cui ti trovi (HEAD).\n"
                              " - 'Usa versione del BRANCH DA UNIRE (--theirs)': Per ogni file in conflitto, usa la versione del branch che stai cercando di unire.\n\n"
                              "Come vuoi procedere?"))
            choices = [
                _("1. Risolvi manualmente i conflitti (poi fai 'add' e 'commit')"),
                _("2. Usa versione del BRANCH CORRENTE per tutti i conflitti (--ours)"),
                _("3. Usa versione del BRANCH DA UNIRE per tutti i conflitti (--theirs)"),
                _("4. Annulla il merge (git merge --abort)")
            ]
            choice_dlg = wx.SingleChoiceDialog(self, dialog_message, _("Gestione Conflitti di Merge"), choices, wx.CHOICEDLG_STYLE)
            if choice_dlg.ShowModal() == wx.ID_OK:
                strategy_choice_text = choice_dlg.GetStringSelection()
                self.output_text_ctrl.AppendText(_("Strategia scelta: {}\n").format(strategy_choice_text))
                if strategy_choice_text == choices[0]:
                    self.output_text_ctrl.AppendText(_("Azione richiesta:\n1. Apri i file in conflitto (elencati sopra) nel tuo editor di testo preferito.\n2. Cerca e risolvi i marcatori di conflitto Git (es. <<<<<<<, =======, >>>>>>>).\n3. Dopo aver risolto tutti i conflitti in un file, usa il comando '{}' per marcare il file come risolto.\n4. Una volta che tutti i file in conflitto sono stati aggiunti, usa il comando '{}' per completare il merge. Puoi lasciare il messaggio di commit vuoto se Git ne propone uno di default.\n").format(CMD_ADD_ALL, CMD_COMMIT))
                elif strategy_choice_text == choices[3]:
                    self.ExecuteGitCommand(CMD_MERGE_ABORT, ORIGINAL_COMMANDS[CMD_MERGE_ABORT], "")
                elif strategy_choice_text == choices[1] or strategy_choice_text == choices[2]:
                    checkout_option = "--ours" if strategy_choice_text == choices[1] else "--theirs"
                    if not conflicting_files_list:
                        self.output_text_ctrl.AppendText(_("Nessun file in conflitto specifico identificato per applicare la strategia automaticamente. Prova a risolvere manualmente o ad annullare.\n")); choice_dlg.Destroy(); return
                    self.output_text_ctrl.AppendText(_("Applicazione della strategia '{}' per i file in conflitto...\n").format(checkout_option)); wx.Yield()
                    all_strategy_applied_successfully = True
                    for f_path in conflicting_files_list:
                        if not self.RunSingleGitCommand(["git", "checkout", checkout_option, "--", f_path], repo_path, _("Applica {} a {}").format(checkout_option, f_path)):
                            all_strategy_applied_successfully = False
                            self.output_text_ctrl.AppendText(_("Attenzione: fallimento nell'applicare la strategia a {}. Controlla l'output.\n").format(f_path))
                    if all_strategy_applied_successfully:
                        self.output_text_ctrl.AppendText(_("Strategia '{}' applicata (o tentata) ai file in conflitto. Ora è necessario aggiungere i file modificati all'area di stage.\n").format(checkout_option)); wx.Yield()
                        add_cmd_details = ORIGINAL_COMMANDS[CMD_ADD_ALL]
                        if self.RunSingleGitCommand(add_cmd_details["cmds"][0], repo_path, _("git add . (post-strategia di merge)")):
                            self.output_text_ctrl.AppendText(_("File modificati aggiunti all'area di stage.\nOra puoi usare il comando '{}' per finalizzare il merge. Lascia il messaggio di commit vuoto se Git ne propone uno.\n").format(CMD_COMMIT))
                        else: self.output_text_ctrl.AppendText(_("ERRORE durante 'git add .' dopo l'applicazione della strategia. Controlla l'output e lo stato del repository. Potrebbe essere necessario un intervento manuale.\n"))
                    else: self.output_text_ctrl.AppendText(_("Alcuni o tutti i file non sono stati processati con successo con la strategia '{}'.\nControlla l'output. Potrebbe essere necessario risolvere manualmente, aggiungere i file e committare, oppure annullare il merge.\n").format(checkout_option))
            choice_dlg.Destroy()
        except Exception as e_conflict:
            self.output_text_ctrl.AppendText(_("Errore durante il tentativo di gestione dei conflitti di merge: {}\nControlla 'git status' per maggiori dettagli.\n").format(e_conflict))
    def OnBrowseRepoPath(self, event):
        current_path = self.repo_path_ctrl.GetValue()
        dlg = wx.DirDialog(self, _("Scegli la cartella del repository Git"),
                           defaultPath=current_path,
                           style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST)
        
        if dlg.ShowModal() == wx.ID_OK:
            new_path = dlg.GetPath()
            if current_path != new_path: # Se il percorso è effettivamente cambiato
                self.repo_path_ctrl.SetValue(new_path) # Questo triggererà OnRepoPathManuallyChanged
                                                       # che a sua volta chiamerà _update_github_context_from_path
                                                       # tramite il timer. Quindi non c'è bisogno di chiamarlo esplicitamente qui.
        dlg.Destroy()
        if hasattr(self, 'statusBar'):
            self.statusBar.SetStatusText(_("Cartella repository impostata a: {}").format(self.repo_path_ctrl.GetValue()))
    def ExecuteDashboardCommand(self, command_name_key, command_details):
        """Gestisce i comandi della dashboard repository."""
        self.output_text_ctrl.AppendText(_("📊 Esecuzione comando Dashboard: {}...\n").format(command_name_key))
        
        repo_path = self.repo_path_ctrl.GetValue()
        if not os.path.isdir(repo_path):
            self.output_text_ctrl.AppendText(_("❌ Errore: Directory repository non valida.\n"))
            return
        
        if not os.path.isdir(os.path.join(repo_path, ".git")):
            self.output_text_ctrl.AppendText(_("❌ Errore: Directory non è un repository Git valido.\n"))
            return
        
        try:
            if command_name_key == CMD_REPO_STATUS_OVERVIEW:
                self._show_repository_overview(repo_path)
            elif command_name_key == CMD_REPO_STATISTICS:
                self._show_repository_statistics(repo_path)
            elif command_name_key == CMD_RECENT_ACTIVITY:
                self._show_recent_activity(repo_path)
            elif command_name_key == CMD_BRANCH_STATUS:
                self._show_branch_status(repo_path)
            elif command_name_key == CMD_FILE_CHANGES_SUMMARY:
                self._show_file_changes_summary(repo_path)
            else:
                self.output_text_ctrl.AppendText(_("❌ Comando dashboard non riconosciuto: {}\n").format(command_name_key))
                
        except Exception as e:
            self.output_text_ctrl.AppendText(_("❌ Errore durante l'esecuzione del comando dashboard: {}\n").format(e))

    # 7. IMPLEMENTA I METODI SPECIFICI DELLA DASHBOARD

    def _show_repository_overview(self, repo_path):
        """Mostra panoramica generale del repository."""
        self.output_text_ctrl.AppendText(_("\n🏠 === PANORAMICA REPOSITORY ===\n"))
        
        process_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        
        try:
            # Nome repository
            repo_name = os.path.basename(repo_path)
            self.output_text_ctrl.AppendText(f"📁 Repository: {repo_name}\n")
            self.output_text_ctrl.AppendText(f"📍 Percorso: {repo_path}\n\n")
            
            # Branch corrente
            result = subprocess.run(["git", "branch", "--show-current"], 
                                  cwd=repo_path, capture_output=True, text=True, 
                                  creationflags=process_flags)
            if result.returncode == 0:
                current_branch = result.stdout.strip()
                self.output_text_ctrl.AppendText(f"🌿 Branch corrente: {current_branch}\n")
            
            # Stato working directory
            result = subprocess.run(["git", "status", "--porcelain"], 
                                  cwd=repo_path, capture_output=True, text=True,
                                  creationflags=process_flags)
            if result.returncode == 0:
                status_lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
                if status_lines and status_lines[0]:
                    self.output_text_ctrl.AppendText(f"📝 File modificati: {len(status_lines)}\n")
                    # Mostra primi 5 file modificati
                    for i, line in enumerate(status_lines[:5]):
                        if line.strip():
                            status_char = line[:2]
                            filename = line[2:]
                            self.output_text_ctrl.AppendText(f"   {status_char} {filename}\n")
                    if len(status_lines) > 5:
                        self.output_text_ctrl.AppendText(f"   ... e altri {len(status_lines) - 5} file\n")
                else:
                    self.output_text_ctrl.AppendText("✅ Working directory pulita\n")
            
            # Ultimo commit
            result = subprocess.run(["git", "log", "-1", "--pretty=format:%h - %s (%cr) <%an>"], 
                                  cwd=repo_path, capture_output=True, text=True,
                                  creationflags=process_flags)
            if result.returncode == 0 and result.stdout:
                self.output_text_ctrl.AppendText(f"📅 Ultimo commit: {result.stdout}\n")
            
            # Remote status
            result = subprocess.run(["git", "remote", "-v"], 
                                  cwd=repo_path, capture_output=True, text=True,
                                  creationflags=process_flags)
            if result.returncode == 0 and result.stdout:
                remotes = [line for line in result.stdout.split('\n') if 'fetch' in line]
                if remotes:
                    self.output_text_ctrl.AppendText(f"🌐 Remote: {remotes[0].split()[1]}\n")
            
            self.output_text_ctrl.AppendText(_("\n✨ Panoramica completata!\n"))
            
        except Exception as e:
            self.output_text_ctrl.AppendText(f"❌ Errore nella panoramica: {e}\n")

    def _show_repository_statistics(self, repo_path):
        """Mostra statistiche dettagliate del repository."""
        self.output_text_ctrl.AppendText(_("\n📊 === STATISTICHE REPOSITORY ===\n"))
        
        process_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        
        try:
            # Numero totale commit
            result = subprocess.run(["git", "rev-list", "--count", "HEAD"], 
                                  cwd=repo_path, capture_output=True, text=True,
                                  creationflags=process_flags)
            if result.returncode == 0:
                total_commits = result.stdout.strip()
                self.output_text_ctrl.AppendText(f"📈 Totale commit: {total_commits}\n")
            
            # Numero contributori
            result = subprocess.run(["git", "shortlog", "-sn", "--all"], 
                                  cwd=repo_path, capture_output=True, text=True,
                                  creationflags=process_flags)
            if result.returncode == 0:
                contributors = result.stdout.strip().split('\n') if result.stdout.strip() else []
                self.output_text_ctrl.AppendText(f"👥 Contributori: {len(contributors)}\n")
                
                # Top 5 contributori
                if contributors:
                    self.output_text_ctrl.AppendText("\n🏆 Top contributori:\n")
                    for i, contributor in enumerate(contributors[:5]):
                        if contributor.strip():
                            parts = contributor.strip().split('\t')
                            if len(parts) >= 2:
                                commits = parts[0]
                                name = parts[1]
                                self.output_text_ctrl.AppendText(f"   {i+1}. {name}: {commits} commits\n")
            
            # Numero branch
            result = subprocess.run(["git", "branch", "-a"], 
                                  cwd=repo_path, capture_output=True, text=True,
                                  creationflags=process_flags)
            if result.returncode == 0:
                branches = [b.strip() for b in result.stdout.split('\n') if b.strip() and not b.strip().startswith('*')]
                local_branches = [b for b in branches if not b.startswith('remotes/')]
                remote_branches = [b for b in branches if b.startswith('remotes/')]
                self.output_text_ctrl.AppendText(f"🌿 Branch locali: {len(local_branches)}\n")
                self.output_text_ctrl.AppendText(f"🌐 Branch remoti: {len(remote_branches)}\n")
            
            # Dimensione repository
            try:
                git_dir_size = 0
                git_dir = os.path.join(repo_path, '.git')
                for dirpath, dirnames, filenames in os.walk(git_dir):
                    for filename in filenames:
                        filepath = os.path.join(dirpath, filename)
                        git_dir_size += os.path.getsize(filepath)
                
                size_mb = git_dir_size / (1024 * 1024)
                self.output_text_ctrl.AppendText(f"💾 Dimensione .git: {size_mb:.1f} MB\n")
            except:
                pass
            
            # File tracciati
            result = subprocess.run(["git", "ls-files"], 
                                  cwd=repo_path, capture_output=True, text=True,
                                  creationflags=process_flags)
            if result.returncode == 0:
                tracked_files = result.stdout.strip().split('\n') if result.stdout.strip() else []
                self.output_text_ctrl.AppendText(f"📄 File tracciati: {len(tracked_files)}\n")
            
            self.output_text_ctrl.AppendText(_("\n✨ Statistiche completate!\n"))
            
        except Exception as e:
            self.output_text_ctrl.AppendText(f"❌ Errore nelle statistiche: {e}\n")

    def _show_recent_activity(self, repo_path):
        """Mostra attività recente nel repository."""
        self.output_text_ctrl.AppendText(_("\n📅 === ATTIVITÀ RECENTE (Ultimi 10 commit) ===\n"))
        
        process_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        
        try:
            result = subprocess.run([
                "git", "log", "--oneline", "--graph", "--decorate", 
                "--pretty=format:%h|%s|%an|%cr", "-10"
            ], cwd=repo_path, capture_output=True, text=True, creationflags=process_flags)
            
            if result.returncode == 0 and result.stdout:
                lines = result.stdout.strip().split('\n')
                for i, line in enumerate(lines):
                    if '|' in line:
                        # Rimuovi i caratteri del graph
                        clean_line = line
                        for char in ['*', '|', '\\', '/', ' ']:
                            if clean_line.startswith(char):
                                clean_line = clean_line[1:]
                            else:
                                break
                        
                        parts = clean_line.split('|')
                        if len(parts) >= 4:
                            hash_val, message, author, time = parts[0], parts[1], parts[2], parts[3]
                            self.output_text_ctrl.AppendText(f"  {i+1:2d}. [{hash_val}] {message}\n")
                            self.output_text_ctrl.AppendText(f"      👤 {author} • ⏰ {time}\n")
                    else:
                        # Linea del graph senza commit info
                        self.output_text_ctrl.AppendText(f"      {line}\n")
                
                self.output_text_ctrl.AppendText(_("\n✨ Attività recente completata!\n"))
            else:
                self.output_text_ctrl.AppendText("❌ Nessun commit trovato o errore nel recupero.\n")
                
        except Exception as e:
            self.output_text_ctrl.AppendText(f"❌ Errore nell'attività recente: {e}\n")

    def _show_branch_status(self, repo_path):
        """Mostra stato dettagliato dei branch."""
        self.output_text_ctrl.AppendText(_("\n🌿 === STATO BRANCH ===\n"))
        
        process_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        
        try:
            # Branch corrente
            result = subprocess.run(["git", "branch", "--show-current"], 
                                  cwd=repo_path, capture_output=True, text=True,
                                  creationflags=process_flags)
            current_branch = result.stdout.strip() if result.returncode == 0 else "unknown"
            
            # Lista tutti i branch locali
            result = subprocess.run(["git", "branch", "-v"], 
                                  cwd=repo_path, capture_output=True, text=True,
                                  creationflags=process_flags)
            
            if result.returncode == 0:
                self.output_text_ctrl.AppendText(f"📍 Branch corrente: {current_branch}\n\n")
                self.output_text_ctrl.AppendText("📋 Tutti i branch locali:\n")
                
                for line in result.stdout.split('\n'):
                    if line.strip():
                        if line.startswith('*'):
                            self.output_text_ctrl.AppendText(f"  ➤ {line[2:]} ← CORRENTE\n")
                        else:
                            self.output_text_ctrl.AppendText(f"    {line.strip()}\n")
            
            # Verifica stato sync con remote
            try:
                result = subprocess.run(["git", "status", "-b", "--porcelain"], 
                                      cwd=repo_path, capture_output=True, text=True,
                                      creationflags=process_flags)
                if result.returncode == 0:
                    status_line = result.stdout.split('\n')[0] if result.stdout else ""
                    if 'ahead' in status_line or 'behind' in status_line:
                        self.output_text_ctrl.AppendText(f"\n📊 Sync status: {status_line}\n")
                    else:
                        self.output_text_ctrl.AppendText(f"\n✅ Branch '{current_branch}' è sincronizzato con remote\n")
            except:
                pass
            
            self.output_text_ctrl.AppendText(_("\n✨ Stato branch completato!\n"))
            
        except Exception as e:
            self.output_text_ctrl.AppendText(f"❌ Errore nello stato branch: {e}\n")

    def _show_file_changes_summary(self, repo_path):
        """Mostra riepilogo delle modifiche ai file."""
        self.output_text_ctrl.AppendText(_("\n📝 === RIEPILOGO MODIFICHE FILE ===\n"))
        
        process_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        
        try:
            # Status dettagliato
            result = subprocess.run(["git", "status", "--porcelain"], 
                                  cwd=repo_path, capture_output=True, text=True,
                                  creationflags=process_flags)
            
            if result.returncode == 0:
                if not result.stdout.strip():
                    self.output_text_ctrl.AppendText("✅ Nessuna modifica pending - working directory pulita!\n")
                    return
                
                # Categorizza le modifiche
                modified = []
                added = []
                deleted = []
                untracked = []
                
                for line in result.stdout.strip().split('\n'):
                    if len(line) >= 2:
                        status = line[:2]
                        filename = line[2:].strip()
                        if status.startswith('M'):
                            modified.append(filename)
                        elif status.startswith('A'):
                            added.append(filename)
                        elif status.startswith('D'):
                            deleted.append(filename)
                        elif status.startswith('??'):
                            untracked.append(filename)
                
                # Mostra summary
                total_changes = len(modified) + len(added) + len(deleted) + len(untracked)
                self.output_text_ctrl.AppendText(f"📊 Totale file modificati: {total_changes}\n\n")
                
                if modified:
                    self.output_text_ctrl.AppendText(f"📝 File modificati ({len(modified)}):\n")
                    for file in modified[:10]:  # Primi 10
                        self.output_text_ctrl.AppendText(f"   M  {file}\n")
                    if len(modified) > 10:
                        self.output_text_ctrl.AppendText(f"   ... e altri {len(modified) - 10} file\n")
                    self.output_text_ctrl.AppendText("\n")
                
                if added:
                    self.output_text_ctrl.AppendText(f"➕ File aggiunti ({len(added)}):\n")
                    for file in added[:10]:
                        self.output_text_ctrl.AppendText(f"   A  {file}\n")
                    if len(added) > 10:
                        self.output_text_ctrl.AppendText(f"   ... e altri {len(added) - 10} file\n")
                    self.output_text_ctrl.AppendText("\n")
                
                if deleted:
                    self.output_text_ctrl.AppendText(f"❌ File eliminati ({len(deleted)}):\n")
                    for file in deleted[:10]:
                        self.output_text_ctrl.AppendText(f"   D  {file}\n")
                    if len(deleted) > 10:
                        self.output_text_ctrl.AppendText(f"   ... e altri {len(deleted) - 10} file\n")
                    self.output_text_ctrl.AppendText("\n")
                
                if untracked:
                    self.output_text_ctrl.AppendText(f"❓ File non tracciati ({len(untracked)}):\n")
                    for file in untracked[:10]:
                        self.output_text_ctrl.AppendText(f"   ?? {file}\n")
                    if len(untracked) > 10:
                        self.output_text_ctrl.AppendText(f"   ... e altri {len(untracked) - 10} file\n")
            
            self.output_text_ctrl.AppendText(_("\n✨ Riepilogo modifiche completato!\n"))
            
        except Exception as e:
            self.output_text_ctrl.AppendText(f"❌ Errore nel riepilogo modifiche: {e}\n")
if __name__ == '__main__':
    app = wx.App(False)
    frame = GitFrame(None)
    app.MainLoop()
