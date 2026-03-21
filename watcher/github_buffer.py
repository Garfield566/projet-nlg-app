# github_buffer.py
"""
Système de buffer pour stocker les requêtes quand le PC est éteint.
Utilise un Gist GitHub comme mémoire tampon.
"""

import json
import requests
import logging
import os
from datetime import datetime

logger = logging.getLogger('nlg-watcher')

class GitHubBuffer:
    def __init__(self, token, gist_id=None):
        self.token = token
        self.gist_id = gist_id or os.environ.get('GITHUB_BUFFER_GIST_ID', '')
        self.api_url = f'https://api.github.com/gists/{self.gist_id}' if self.gist_id else None
        self.buffer_file = 'requests_buffer.json'
        
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
        
        issue_data['buffered_at'] = datetime.now().isoformat()
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
