class GitHubBuffer:
    """Système de buffer pour stocker les requêtes quand le PC est éteint"""
    
    def __init__(self, token, gist_id=None):
        self.token = token
        self.gist_id = gist_id or GITHUB_BUFFER_GIST_ID
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
                    'content': json.dumps([], indent=2, ensure_ascii=False)
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
            try:
                with open('.buffer_gist_id', 'w', encoding='utf-8') as f:
                    f.write(self.gist_id)
                logger.info('ID du buffer sauvegardé dans .buffer_gist_id')
            except Exception as e:
                logger.warning(f'Impossible de sauvegarder l\'ID du buffer: {e}')
            
            return self.gist_id
        except requests.exceptions.RequestException as e:
            logger.error(f'Erreur lors de la création du buffer: {e}')
            return None
    
    def get_buffer(self):
        """Récupère toutes les requêtes en attente dans le buffer"""
        if not self.api_url:
            logger.debug('Buffer non configuré (pas d\'URL API)')
            return []
            
        try:
            headers = {
                'Authorization': f'Bearer {self.token}',
                'Accept': 'application/vnd.github+json'
            }
            resp = requests.get(self.api_url, headers=headers, timeout=15)
            resp.raise_for_status()
            gist = resp.json()
            
            # Vérifier si le fichier existe dans le gist
            if self.buffer_file not in gist.get('files', {}):
                logger.warning(f'Fichier {self.buffer_file} non trouvé dans le gist')
                return []
            
            content = gist['files'][self.buffer_file].get('content', '[]')
            
            # Vérifier que le contenu est valide
            if not content or content.strip() == '':
                return []
                
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f'Erreur de décodage JSON du buffer: {e}')
            return []
        except requests.exceptions.RequestException as e:
            logger.error(f'Erreur lors de la lecture du buffer: {e}')
            return []
    
    def save_buffer(self, buffer_data):
        """Sauvegarde les données dans le buffer"""
        if not self.api_url:
            logger.warning('Impossible de sauvegarder: buffer non configuré')
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
                        'content': json.dumps(buffer_data, indent=2, ensure_ascii=False)
                    }
                }
            }
            resp = requests.patch(self.api_url, headers=headers, json=data, timeout=15)
            resp.raise_for_status()
            logger.debug(f'Buffer sauvegardé avec succès ({len(buffer_data)} entrées)')
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f'Erreur lors de la sauvegarde du buffer: {e}')
            return False
    
    def add_request(self, issue_number, title, body):
        """Ajoute une requête au buffer"""
        try:
            # Récupérer le buffer actuel
            buffer = self.get_buffer()
            
            # Vérifier si la requête existe déjà
            for req in buffer:
                if req.get('issue_number') == issue_number:
                    logger.debug(f'Requête #{issue_number} déjà dans le buffer')
                    return False
            
            # Créer la nouvelle entrée
            new_request = {
                'issue_number': issue_number,
                'title': title,
                'body': body,
                'status': 'pending',
                'buffered_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            
            buffer.append(new_request)
            
            # Sauvegarder
            if self.save_buffer(buffer):
                logger.info(f'Requête #{issue_number} ajoutée au buffer')
                return True
            else:
                logger.error(f'Échec de sauvegarde pour la requête #{issue_number}')
                return False
                
        except Exception as e:
            logger.error(f'Erreur lors de l\'ajout au buffer: {e}')
            return False
    
    def remove_request(self, issue_number):
        """Supprime une requête du buffer après traitement"""
        try:
            buffer = self.get_buffer()
            original_count = len(buffer)
            
            # Filtrer pour enlever la requête
            buffer = [req for req in buffer if req.get('issue_number') != issue_number]
            
            if len(buffer) < original_count:
                if self.save_buffer(buffer):
                    logger.info(f'Requête #{issue_number} retirée du buffer')
                    return True
                else:
                    logger.error(f'Échec de suppression pour la requête #{issue_number}')
                    return False
            else:
                logger.debug(f'Requête #{issue_number} non trouvée dans le buffer')
                return True
                
        except Exception as e:
            logger.error(f'Erreur lors de la suppression du buffer: {e}')
            return False
    
    def get_pending_requests(self):
        """Récupère toutes les requêtes en attente"""
        try:
            buffer = self.get_buffer()
            pending = [req for req in buffer if req.get('status') == 'pending']
            logger.debug(f'{len(pending)} requête(s) en attente dans le buffer')
            return pending
        except Exception as e:
            logger.error(f'Erreur lors de la récupération des requêtes en attente: {e}')
            return []
    
    def mark_as_processing(self, issue_number):
        """Marque une requête comme en cours de traitement"""
        try:
            buffer = self.get_buffer()
            for req in buffer:
                if req.get('issue_number') == issue_number:
                    req['status'] = 'processing'
                    req['processing_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
                    return self.save_buffer(buffer)
            return False
        except Exception as e:
            logger.error(f'Erreur lors du marquage en traitement: {e}')
            return False
    
    def clear_buffer(self):
        """Vide complètement le buffer"""
        try:
            if self.save_buffer([]):
                logger.info('Buffer vidé avec succès')
                return True
            else:
                logger.error('Échec du vidage du buffer')
                return False
        except Exception as e:
            logger.error(f'Erreur lors du vidage du buffer: {e}')
            return False
    
    def get_buffer_stats(self):
        """Retourne des statistiques sur le buffer"""
        try:
            buffer = self.get_buffer()
            total = len(buffer)
            pending = len([r for r in buffer if r.get('status') == 'pending'])
            processing = len([r for r in buffer if r.get('status') == 'processing'])
            
            return {
                'total': total,
                'pending': pending,
                'processing': processing,
                'gist_id': self.gist_id
            }
        except Exception as e:
            logger.error(f'Erreur lors du calcul des statistiques: {e}')
            return {'total': 0, 'pending': 0, 'processing': 0, 'gist_id': None}
