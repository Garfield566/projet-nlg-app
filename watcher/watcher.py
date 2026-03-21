"""
Watcher GitHub → generation locale.
Tourne en fond sur le PC. Poll les Issues GitHub labellees 'nlg-request' 
et les requêtes stockées dans le buffer Gist.
Execute la generation (note ou canvas), commente le resultat et ferme l'Issue.

Usage:
    python watcher.py

Variables d'environnement:
    GITHUB_TOKEN  — token GitHub (obligatoire)
    GITHUB_REPO   — owner/name du repo (obligatoire)
    GITHUB_BUFFER_GIST_ID — ID du Gist buffer (optionnel)
    POLL_INTERVAL — secondes entre chaque poll (defaut: 30)
"""

import os
import sys
import json
import time
import re
import traceback
import logging

import requests

# Setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('nlg-watcher')

GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
GITHUB_REPO = os.environ.get('GITHUB_REPO', '')
GITHUB_BUFFER_GIST_ID = os.environ.get('GITHUB_BUFFER_GIST_ID', '')
POLL_INTERVAL = int(os.environ.get('POLL_INTERVAL', '30'))

# Backend path
BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend')
sys.path.insert(0, BACKEND_DIR)

GITHUB_API = 'https://api.github.com'
BUFFER_FILE = 'requests_buffer.json'


class GitHubBuffer:
    """Système de buffer pour stocker les requêtes quand le PC est éteint"""
    
    def __init__(self, token, gist_id=None):
        self.token = token
        self.gist_id = gist_id or GITHUB_BUFFER_GIST_ID
        self.api_url = f'https://api.github.com/gists/{self.gist_id}' if self.gist_id else None
        self.buffer_file = BUFFER_FILE
        
    def create_buffer_gist(self):
        """Crée un nouveau Gist pour le buffer si nécessaire"""
        url = 'https://api.github.com/gists'
        headers = {
            'Authorization': f'Bearer {self.token}',
            'Accept': 'application/vnd.github+json'
        }
        data = {
            'description': 'Buffer pour les requêtes NLG (PC éteint)',
            'public': False,
            'files': {
                self.buffer_file: {
                    'content': json.dumps([], indent=2)
                }
            }
        }
        
        try:
            resp = requests.post(url, headers=headers, json=data, timeout=15)
            resp.raise_for_status()
            gist = resp.json()
            self.gist_id = gist['id']
            self.api_url = f'https://api.github.com/gists/{self.gist_id}'
            logger.info(f'Buffer Gist créé: {self.gist_id}')
            
            # Sauvegarder l'ID pour la prochaine fois
            with open('.buffer_gist_id', 'w') as f:
                f.write(self.gist_id)
            
            return self.gist_id
        except Exception as e:
            logger.error(f'Erreur création buffer: {e}')
            return None
    
    def get_buffer(self):
        """Récupère toutes les requêtes en attente"""
        if not self.api_url:
            logger.warning('Buffer non configuré')
            return []
            
        try:
            headers = {
                'Authorization': f'Bearer {self.token}',
                'Accept': 'application/vnd.github+json'
            }
            resp = requests.get(self.api_url, headers=headers, timeout=15)
            resp.raise_for_status()
            gist = resp.json()
            content = gist['files'].get(self.buffer_file, {}).get('content', '[]')
            return json.loads(content)
        except Exception as e:
            logger.error(f'Erreur lecture buffer: {e}')
            return []
    
    def save_buffer(self, buffer):
        """Sauvegarde le buffer dans le Gist"""
        if not self.api_url:
            return False
            
        try:
            headers = {
                'Authorization': f'Bearer {self.token}',
                'Content-Type': 'application/json',
                'Accept': 'application/vnd.github+json'
            }
            data = {
                'files': {
                    self.buffer_file: {
                        'content': json.dumps(buffer, indent=2, ensure_ascii=False)
                    }
                }
            }
            resp = requests.patch(self.api_url, headers=headers, json=data, timeout=15)
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f'Erreur sauvegarde buffer: {e}')
            return False
    
    def add_request(self, issue_data):
        """Ajoute une requête au buffer (quand le PC est éteint)"""
        buffer = self.get_buffer()
        
        # Vérifier si la requête existe déjà
        for req in buffer:
            if req.get('issue_number') == issue_data.get('issue_number'):
                logger.debug(f'Requête #{issue_data["issue_number"]} déjà dans le buffer')
                return False
        
        issue_data['buffered_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        issue_data['status'] = 'pending'
        buffer.append(issue_data)
        
        if self.save_buffer(buffer):
            logger.info(f'Requête #{issue_data["issue_number"]} ajoutée au buffer')
            return True
        return False
    
    def remove_request(self, issue_number):
        """Supprime une requête du buffer après traitement"""
        buffer = self.get_buffer()
        buffer = [req for req in buffer if req.get('issue_number') != issue_number]
        
        if self.save_buffer(buffer):
            logger.info(f'Requête #{issue_number} retirée du buffer')
            return True
        return False
    
    def get_pending_requests(self):
        """Récupère toutes les requêtes en attente"""
        buffer = self.get_buffer()
        return [req for req in buffer if req.get('status') == 'pending']
    
    def clear_buffer(self):
        """Vide le buffer (après traitement complet)"""
        return self.save_buffer([])


def github_headers():
    return {
        'Authorization': f'Bearer {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github+json',
    }


def fetch_open_issues():
    """Recupere les Issues ouvertes avec le label nlg-request."""
    url = f'{GITHUB_API}/repos/{GITHUB_REPO}/issues'
    params = {'labels': 'nlg-request', 'state': 'open', 'per_page': 50}
    resp = requests.get(url, headers=github_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_open_issues_with_buffer():
    """Récupère les Issues ouvertes + celles dans le buffer"""
    buffer_requests = []
    
    # Initialiser le buffer
    buffer = GitHubBuffer(GITHUB_TOKEN)
    
    # Si le buffer n'a pas de Gist ID, essayer d'en charger un ou en créer
    if not buffer.gist_id:
        # Essayer de charger l'ID sauvegardé
        if os.path.exists('.buffer_gist_id'):
            with open('.buffer_gist_id', 'r') as f:
                saved_id = f.read().strip()
                if saved_id:
                    buffer.gist_id = saved_id
                    buffer.api_url = f'https://api.github.com/gists/{saved_id}'
        
        # Si toujours pas d'ID, en créer un
        if not buffer.gist_id:
            buffer.create_buffer_gist()
    
    # Récupérer les requêtes en attente du buffer
    try:
        buffer_requests = buffer.get_pending_requests()
        if buffer_requests:
            logger.info(f'{len(buffer_requests)} requête(s) dans le buffer')
    except Exception as e:
        logger.error(f'Erreur récupération buffer: {e}')
    
    # Récupérer les issues GitHub actuelles
    try:
        github_issues = fetch_open_issues()
    except Exception as e:
        logger.error(f'Erreur récupération issues: {e}')
        github_issues = []
    
    # Convertir les requêtes du buffer en format "issue" pour traitement
    buffer_as_issues = []
    for req in buffer_requests:
        buffer_as_issues.append({
            'number': req['issue_number'],
            'title': req.get('title', 'Buffered Request'),
            'body': req.get('body', ''),
            'buffer_request': True  # Marqueur pour identifier les requêtes bufferisées
        })
    
    return buffer_as_issues + github_issues


def parse_issue_body(body):
    """Extrait le JSON de commande du body de l'Issue."""
    match = re.search(r'```json\s*\n(.*?)\n```', body, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def comment_issue(issue_number, message):
    """Ajoute un commentaire a l'Issue."""
    url = f'{GITHUB_API}/repos/{GITHUB_REPO}/issues/{issue_number}/comments'
    requests.post(url, headers=github_headers(), json={'body': message}, timeout=15)


def close_issue(issue_number):
    """Ferme l'Issue."""
    url = f'{GITHUB_API}/repos/{GITHUB_REPO}/issues/{issue_number}'
    requests.patch(url, headers=github_headers(), json={'state': 'closed'}, timeout=15)


def process_note(cmd, issue_number, is_buffered=False):
    """Genere une note."""
    from extraction.wikipedia import ExtracteurWikipedia
    from wikidata.cache import CacheWikidata
    from wikidata.client import ClientWikidata
    from wikidata.resolver import ResolveurWikidata
    from wikidata.extractor import ExtracteurWikidata as ExtWD
    from wikidata.extractors.generic import GenericExtractor
    from gen_all_templates import build_generic_note, OUTPUT_DIR
    from utils.graph_injector import get_graph_section
    from utils.encoding import reparer_encodage

    sujet = cmd.get('sujet', '').strip()
    categorie = cmd.get('categorie', 'concept').strip()
    
    buffer = GitHubBuffer(GITHUB_TOKEN)

    if not is_buffered:
        comment_issue(issue_number, f'Generation en cours pour **{sujet}** ({categorie})...')
    else:
        logger.info(f'Traitement requête bufferisée: {sujet}')

    cache = CacheWikidata()
    wd_client = ClientWikidata(cache=cache)
    ext = ExtracteurWikipedia()
    wd_ext = ExtWD(wd_client)
    generic_ext = GenericExtractor(wd_ext, wd_client)
    resolveur = ResolveurWikidata(wd_client)

    # Resoudre QID
    qid = resolveur.resoudre(sujet, categorie)
    if not qid:
        if not is_buffered:
            comment_issue(issue_number, f'QID non trouve pour **{sujet}**')
            close_issue(issue_number)
        else:
            buffer.remove_request(issue_number)
        return

    # Extraire Wikipedia
    wiki = ext.extraire_par_qid(qid, categorie)
    if not wiki or not wiki.get('succes'):
        wiki = ext.extraire_donnees(sujet, categorie)
        if not wiki or not wiki.get('succes'):
            entite = wd_client.obtenir_entite(qid)
            if entite:
                label_fr = entite.get('labels', {}).get('fr', {}).get('value', '')
                if label_fr:
                    wiki = ext.extraire_donnees(label_fr, categorie)

    # Extraire Wikidata
    fiche_wd = None
    entite_wd = wd_client.obtenir_entite(qid)
    if entite_wd:
        fiche_wd = generic_ext.extraire(entite_wd)

    # Generer
    content = build_generic_note(sujet, qid, categorie, wiki, fiche_wd=fiche_wd)

    # TikZ
    graph_section = get_graph_section(qid, sujet, categorie)
    if graph_section:
        content = content.rstrip('\n') + '\n\n' + graph_section

    content = reparer_encodage(content)

    # Ecrire
    safe = sujet.replace('/', '-').replace('\\', '-')
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, f'{safe}.md')
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    mots = len(content.split())
    
    if not is_buffered:
        comment_issue(issue_number,
            f'Note generee pour **{sujet}** ({qid})\n'
            f'- {mots} mots\n'
            f'- Fichier: `{filepath}`'
        )
        close_issue(issue_number)
    else:
        # Pour une requête bufferisée, on ne commente pas l'issue originale
        logger.info(f'Note generee (buffer): {sujet} ({mots} mots) -> {filepath}')
        buffer.remove_request(issue_number)
    
    logger.info('Note generee: %s (%d mots)', sujet, mots)


def process_canvas(cmd, issue_number, is_buffered=False):
    """Genere un canvas."""
    from canvas_pipeline.config import PipelineConfig
    from canvas_pipeline.pipeline import CanvasPipeline

    sujet = cmd.get('sujet', '').strip()
    mode = cmd.get('mode', 'normal').strip()
    template = cmd.get('template') or None
    
    buffer = GitHubBuffer(GITHUB_TOKEN)

    if not is_buffered:
        comment_issue(issue_number, f'Generation canvas en cours pour **{sujet}** (mode: {mode})...')
    else:
        logger.info(f'Traitement canvas bufferisé: {sujet}')

    vault_path = os.environ.get(
        'NLG_VAULT_PATH',
        r'C:\Users\robin tual\quartz\content',
    )
    config = PipelineConfig.from_vault(vault_path)
    pipeline = CanvasPipeline(config=config, vault_path=vault_path)

    safe = sujet.replace('/', '_').replace('\\', '_').replace(' ', '_')
    output_base = os.environ.get('NLG_OUTPUT_DIR')
    if output_base:
        output_dir = os.path.join(os.path.dirname(output_base), 'canva')
    else:
        output_dir = os.path.join(vault_path, 'Teste-generator', 'canva')
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f'{safe}.canvas')

    if template:
        template = template.lower()

    # Redirect stdout to avoid pollution
    _real_stdout = sys.stdout
    sys.stdout = sys.stderr

    try:
        if mode == 'tag':
            if '|' in sujet:
                tag_list = [t.strip() for t in sujet.split('|')]
                tag_mode = 'or'
            else:
                tag_list = [t.strip() for t in sujet.split(',')]
                tag_mode = 'and'
            result = pipeline.run_from_tags(
                tags=tag_list, output_path=output_path,
                mode=tag_mode, template=template,
            )
        elif mode == 'dossier':
            result = pipeline.run_from_folder(
                folder=sujet, output_path=output_path, template=template,
            )
        else:
            result = pipeline.run(
                subject=sujet, output_path=output_path,
                template=template, no_prompt=True,
            )
    finally:
        sys.stdout = _real_stdout

    noeuds = len(getattr(result.canvas, 'nodes', []))
    
    if not is_buffered:
        comment_issue(issue_number,
            f'Canvas genere pour **{sujet}**\n'
            f'- {noeuds} noeuds\n'
            f'- Template: {result.template_name}\n'
            f'- Fichier: `{output_path}`'
        )
        close_issue(issue_number)
    else:
        # Pour une requête bufferisée, on ne commente pas l'issue originale
        logger.info(f'Canvas generee (buffer): {sujet} ({noeuds} noeuds) -> {output_path}')
        buffer.remove_request(issue_number)
    
    logger.info('Canvas genere: %s (%d noeuds)', sujet, noeuds)


def process_issue(issue):
    """Traite une Issue GitHub ou une requête bufferisée."""
    issue_number = issue['number']
    body = issue.get('body', '')
    title = issue.get('title', '')
    is_buffered = issue.get('buffer_request', False)
    
    buffer = GitHubBuffer(GITHUB_TOKEN)

    cmd = parse_issue_body(body)
    if not cmd:
        if not is_buffered:
            comment_issue(issue_number, 'Format de commande invalide (JSON manquant)')
            close_issue(issue_number)
        else:
            # Si c'est une requête bufferisée invalide, la supprimer
            buffer.remove_request(issue_number)
        return

    action = cmd.get('action', '')
    logger.info('Issue #%d: %s — %s %s', issue_number, title, action, 
                '(bufferisé)' if is_buffered else '')

    try:
        if action == 'generate_note':
            process_note(cmd, issue_number, is_buffered)
        elif action == 'generate_canvas':
            process_canvas(cmd, issue_number, is_buffered)
        else:
            if not is_buffered:
                comment_issue(issue_number, f'Action inconnue: {action}')
                close_issue(issue_number)
            else:
                buffer.remove_request(issue_number)
    except Exception as e:
        logger.error('Erreur Issue #%d: %s', issue_number, e)
        traceback.print_exc()
        if not is_buffered:
            comment_issue(issue_number, f'Erreur: {e}')
            close_issue(issue_number)
        else:
            buffer.remove_request(issue_number)


def main():
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print('Variables manquantes:')
        print('  GITHUB_TOKEN=ghp_xxx')
        print('  GITHUB_REPO=owner/repo')
        sys.exit(1)

    logger.info('NLG Watcher demarre')
    logger.info('Repo: %s', GITHUB_REPO)
    logger.info('Poll: toutes les %ds', POLL_INTERVAL)
    logger.info('Backend: %s', BACKEND_DIR)
    
    # Initialiser le buffer
    buffer = GitHubBuffer(GITHUB_TOKEN)
    if not buffer.gist_id:
        # Essayer de charger l'ID sauvegardé
        if os.path.exists('.buffer_gist_id'):
            with open('.buffer_gist_id', 'r') as f:
                saved_id = f.read().strip()
                if saved_id:
                    buffer.gist_id = saved_id
                    buffer.api_url = f'https://api.github.com/gists/{saved_id}'
                    logger.info(f'Buffer Gist chargé: {saved_id}')
        
        # Si toujours pas d'ID, en créer un
        if not buffer.gist_id:
            buffer.create_buffer_gist()
            logger.info('Buffer Gist créé automatiquement')
    
    if buffer.gist_id:
        logger.info('Buffer actif: %s', buffer.gist_id)

    while True:
        try:
            # Récupérer les issues (GitHub + Buffer)
            all_requests = fetch_open_issues_with_buffer()
            
            if all_requests:
                logger.info('%d requete(s) en attente', len(all_requests))
                for request in all_requests:
                    process_issue(request)
            else:
                logger.debug('Aucune requete')
        except KeyboardInterrupt:
            logger.info('Arret')
            break
        except Exception as e:
            logger.error('Erreur poll: %s', e)
            traceback.print_exc()

        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
