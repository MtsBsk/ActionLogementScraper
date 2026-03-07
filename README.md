# Action Logement Scraper - Alertes nouveaux logements

Script automatique qui surveille les nouveaux logements sur [al-in.fr](https://al-in.fr/) (Action Logement) et envoie des alertes par email via [Resend](https://resend.com/).

Tourne gratuitement sur GitHub Actions (repo public) toutes les 5 minutes.

## Configuration

### 1. Creer un compte Resend

1. Inscris-toi sur [resend.com](https://resend.com/)
2. Recupere ta cle API dans le dashboard
3. (Optionnel) Configure un domaine d'envoi personnalise, sinon utilise `onboarding@resend.dev`

### 2. Configurer le repo GitHub

Dans les **Settings** du repo :

**Secrets** (`Settings > Secrets and variables > Actions > Secrets`) :
- `RESEND_API_KEY` : ta cle API Resend

**Variables** (`Settings > Secrets and variables > Actions > Variables`) :
- `EMAIL_TO` : ton adresse email (ex: `monemail@gmail.com`)
- `EMAIL_FROM` : adresse d'envoi (ex: `onboarding@resend.dev` ou ton domaine)
- `FILTER_DEPARTMENTS` : numeros de departements, separes par des virgules (defaut: `75,92,93,94`)
- `FILTER_MAX_RENT` : loyer max charges comprises en EUR (defaut: `0` = pas de limite)
- `FILTER_MIN_ROOMS` : nombre de pieces minimum (defaut: `0` = pas de limite)
- `FILTER_MAX_ROOMS` : nombre de pieces maximum (defaut: `0` = pas de limite)
- `FILTER_MIN_SURFACE` : surface minimale en m2 (defaut: `0` = pas de limite)
- `FILTER_TYPOLOGIES` : types de logement, separes par des virgules (defaut: vide = tous)

### Departements disponibles

| Code | Departement |
|------|-------------|
| 75 | Paris |
| 77 | Seine-et-Marne |
| 78 | Yvelines |
| 91 | Essonne |
| 92 | Hauts-de-Seine |
| 93 | Seine-Saint-Denis |
| 94 | Val-de-Marne |
| 95 | Val-d'Oise |
| 06 | Alpes-Maritimes |
| 13 | Bouches-du-Rhone |
| 31 | Haute-Garonne |
| 33 | Gironde |
| 34 | Herault |
| 35 | Ille-et-Vilaine |
| 44 | Loire-Atlantique |
| 59 | Nord |
| 67 | Bas-Rhin |
| 69 | Rhone |

> Tout numero de departement francais est utilisable, cette liste est donnee a titre indicatif.

### Typologies disponibles

| Code | Type |
|------|------|
| T1 | 1 piece |
| T1BIS | 1 piece bis |
| T2 | 2 pieces |
| T3 | 3 pieces |
| T4 | 4 pieces |
| T5 | 5 pieces et plus |

> Laisse une variable vide pour ne pas filtrer sur ce critere.

### 3. Activer GitHub Actions

Le workflow se declenche automatiquement toutes les 5 minutes. Tu peux aussi le lancer manuellement :
- Va dans l'onglet **Actions** du repo
- Selectionne **Scrape Action Logement**
- Clique sur **Run workflow**

## Test local

```bash
pip install -r requirements.txt

# Avec les filtres par defaut (Paris + petite couronne)
python scraper.py

# Ou avec des filtres personnalises
FILTER_DEPARTMENTS="75,92" FILTER_MAX_RENT="800" FILTER_TYPOLOGIES="T2,T3" python scraper.py
```

> Sans `RESEND_API_KEY`, le script affiche les offres dans la console au lieu d'envoyer un email.

## Fonctionnement

1. Appelle l'API publique d'al-in.fr avec les filtres de departement configures
2. Applique les filtres supplementaires (loyer, pieces, surface, typologie) cote client
3. Compare les offres avec celles deja vues (cache GitHub Actions)
4. Envoie un email via Resend si de nouveaux logements sont detectes
5. Met a jour le cache des offres vues
