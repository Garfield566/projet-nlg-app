"""Watcher GitHub → generation locale.

Tourne en fond sur le PC. Poll les Issues GitHub labellees 'nlg-request',
execute la generation (note ou canvas), commente le resultat et ferme l'Issue.

Usage:
    python watcher.py

Variables d'environnement:
    GITHUB_TOKEN  — token GitHub (obligatoire)
    GITHUB_REPO   — owner/name du repo (obligatoire)
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
POLL_INTERVAL = int(os.environ.get('POLL_INTERVAL', '30'))

# Backend path
BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend')
sys.path.insert(0, BACKEND_DIR)

GITHUB_API = 'https://api.github.com'


def github_headers():
    return {
        'Authorization': f'Bearer {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github+json',
    }


def fetch_open_issues():
    """Recupere les Issues ouvertes avec le label nlg-request."""
    url = f'{GITHUB_API}/repos/{GITHUB_REPO}/issues'
    params = {'labels': 'nlg-request', 'state': 'open', 'per_page': 10}
    resp = requests.get(url, headers=github_headers(), params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


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


def process_note(cmd, issue_number):
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

    comment_issue(issue_number, f'Generation en cours pour **{sujet}** ({categorie})...')

    cache = CacheWikidata()
    wd_client = ClientWikidata(cache=cache)
    ext = ExtracteurWikipedia()
    wd_ext = ExtWD(wd_client)
    generic_ext = GenericExtractor(wd_ext, wd_client)
    resolveur = ResolveurWikidata(wd_client)

    # Resoudre QID
    qid = resolveur.resoudre(sujet, categorie)
    if not qid:
        comment_issue(issue_number, f'QID non trouve pour **{sujet}**')
        close_issue(issue_number)
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
    comment_issue(issue_number,
        f'Note generee pour **{sujet}** ({qid})\n'
        f'- {mots} mots\n'
        f'- Fichier: `{filepath}`'
    )
    close_issue(issue_number)
    logger.info('Note generee: %s (%d mots)', sujet, mots)


def process_canvas(cmd, issue_number):
    """Genere un canvas."""
    from canvas_pipeline.config import PipelineConfig
    from canvas_pipeline.pipeline import CanvasPipeline

    sujet = cmd.get('sujet', '').strip()
    mode = cmd.get('mode', 'normal').strip()
    template = cmd.get('template') or None

    comment_issue(issue_number, f'Generation canvas en cours pour **{sujet}** (mode: {mode})...')

    vault_path = os.environ.get(
        'NLG_VAULT_PATH',
        r'C:\Users\3TTT\OneDrive\obsidiane\Cerveau',
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
    comment_issue(issue_number,
        f'Canvas genere pour **{sujet}**\n'
        f'- {noeuds} noeuds\n'
        f'- Template: {result.template_name}\n'
        f'- Fichier: `{output_path}`'
    )
    close_issue(issue_number)
    logger.info('Canvas genere: %s (%d noeuds)', sujet, noeuds)


def process_issue(issue):
    """Traite une Issue GitHub."""
    issue_number = issue['number']
    body = issue.get('body', '')
    title = issue.get('title', '')

    cmd = parse_issue_body(body)
    if not cmd:
        comment_issue(issue_number, 'Format de commande invalide (JSON manquant)')
        close_issue(issue_number)
        return

    action = cmd.get('action', '')
    logger.info('Issue #%d: %s — %s', issue_number, title, action)

    try:
        if action == 'generate_note':
            process_note(cmd, issue_number)
        elif action == 'generate_canvas':
            process_canvas(cmd, issue_number)
        else:
            comment_issue(issue_number, f'Action inconnue: {action}')
            close_issue(issue_number)
    except Exception as e:
        logger.error('Erreur Issue #%d: %s', issue_number, e)
        traceback.print_exc()
        comment_issue(issue_number, f'Erreur: {e}')
        close_issue(issue_number)


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

    while True:
        try:
            issues = fetch_open_issues()
            if issues:
                logger.info('%d requete(s) en attente', len(issues))
                for issue in issues:
                    process_issue(issue)
            else:
                logger.debug('Aucune requete')
        except KeyboardInterrupt:
            logger.info('Arret')
            break
        except Exception as e:
            logger.error('Erreur poll: %s', e)

        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
