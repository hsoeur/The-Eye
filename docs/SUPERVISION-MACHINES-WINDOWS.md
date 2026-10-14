# Superviser une machine Windows depuis The Eye (WinRM)

Procédure à reproduire pour chaque nouvelle machine Windows.
Vocabulaire :

- **Serveur The Eye** : la machine qui héberge The Eye (ici `192.168.1.104`).
- **Machine cible** : la machine à superviser (ici `192.168.1.102` et `192.168.1.101`).

Toutes les commandes se lancent dans un **PowerShell ouvert en administrateur**.

## 1. Choisir le compte

The Eye se connecte à la cible avec un compte qui doit être **administrateur local** de la cible.

| Type de compte | Format à saisir dans The Eye |
|---|---|
| Compte de domaine | `DOMAINE\Compte` (ici `AMPHI-PROD\AdminDMZ`) |
| Compte local de la cible | `NOMMACHINE\Compte` |

Un compte de domaine est la solution la plus simple : un seul mot de passe pour toutes les machines du domaine, et aucune étape UAC (voir 2.3).
Pour connaître le domaine d'une machine : `(Get-CimInstance Win32_ComputerSystem).Domain`.

Le mot de passe ne doit pas être vide.

## 2. Sur la machine cible

### 2.1 Activer WinRM

```powershell
Enable-PSRemoting -Force -SkipNetworkProfileCheck
```

Cette commande démarre le service WinRM, crée l'écouteur sur le port **5985** et ouvre le pare-feu.

### 2.2 Vérifier que le compte est administrateur local

```powershell
Get-LocalGroupMember Administrateurs
```

Le compte doit apparaître dans la liste, directement ou via un groupe du domaine. Sinon :

```powershell
Add-LocalGroupMember -Group Administrateurs -Member "DOMAINE\Compte"
```

### 2.3 Lever le filtrage UAC distant (comptes locaux uniquement)

À faire seulement si le compte est un **compte local** autre que l'`Administrateur` intégré. Sans cela, la connexion échoue avec « Accès refusé » :

```powershell
New-ItemProperty HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System `
  -Name LocalAccountTokenFilterPolicy -Value 1 -PropertyType DWord -Force
```

Aucun redémarrage n'est nécessaire. Ce réglage permet aux administrateurs locaux d'utiliser tous leurs droits à distance : acceptable sur un réseau interne de supervision, à éviter sur un réseau exposé.

## 3. Sur le serveur The Eye (une fois par machine cible)

WinRM refuse de se connecter à une **adresse IP** inconnue. Il faut l'ajouter à la liste `TrustedHosts`.

Pour ne pas écraser la liste existante, lis-la d'abord :

```powershell
Get-Item WSMan:\localhost\Client\TrustedHosts
```

Puis redéfinis-la en y ajoutant la nouvelle IP, séparée par des virgules :

```powershell
Set-Item WSMan:\localhost\Client\TrustedHosts -Value "192.168.1.102,192.168.1.101,<nouvelle IP>" -Force
```

Le changement est immédiat. Pour autoriser tout un sous-réseau, utilise `"192.168.1.*"` : c'est pratique, mais moins sûr.

## 4. Tester la connexion (recommandé)

Depuis le serveur The Eye, avant de passer par l'interface :

```powershell
Enter-PSSession -ComputerName <IP de la cible> -Credential (Get-Credential DOMAINE\Compte)
```

Si le prompt `[IP]: PS>` apparaît, la connexion marche. Quitte avec `exit`.
Ce test isole les problèmes de réseau, de droits ou de mot de passe, sans passer par The Eye.

Test du port depuis le serveur The Eye :

```powershell
Test-NetConnection <IP de la cible> -Port 5985
```

`TcpTestSucceeded : True` est attendu.

## 5. Ajouter la machine dans The Eye

1. Ouvre `http://192.168.1.104:8765`, onglet **🖥️ Machines**.
2. Renseigne l'IP, le type (Windows), l'utilisateur au format de la section 1 et le mot de passe.
3. Valide : la carte passe au vert après quelques secondes, avec les services, processus, disques, ports et événements.

Les mots de passe sont stockés chiffrés (DPAPI) dans `C:\TheEye\data\hosts.json`. Ce chiffrement est lié au compte qui exécute la tâche planifiée `TheEye` : si ce compte change, il faut ressaisir les mots de passe.

## 6. Dépannage

| Message dans The Eye | Cause | Solution |
|---|---|---|
| « L'authentification par défaut peut être utilisée avec une adresse IP dans les conditions suivantes… » | L'IP n'est pas dans TrustedHosts | Section 3 |
| « Accès refusé » | Mauvais format de compte, mot de passe incorrect, compte non administrateur, ou filtrage UAC | Sections 1, 2.2 et 2.3, puis test de la section 4 |
| Délai dépassé / impossible de se connecter | WinRM inactif, pare-feu ou réseau | Section 2.1, puis `Test-NetConnection … -Port 5985` |

Cas rencontré : une machine refusait la connexion avec `VM-DEVOPS\AdminDMZ`, alors qu'elle était dans le domaine. Le compte à utiliser était `AMPHI-PROD\AdminDMZ`. En cas de « Accès refusé », essaie d'abord l'autre format (domaine ou nom de machine).

Pour des machines **Linux**, la supervision passe par SSH : ajoute la machine avec le type Linux, un utilisateur SSH et son mot de passe. WinRM n'est pas utilisé.

## 7. Récapitulatif

Pour chaque nouvelle machine Windows :

- [ ] Sur la cible : `Enable-PSRemoting -Force -SkipNetworkProfileCheck`
- [ ] Sur la cible : le compte est administrateur local
- [ ] Sur la cible (compte local uniquement) : `LocalAccountTokenFilterPolicy = 1`
- [ ] Sur le serveur The Eye : l'IP est ajoutée à `TrustedHosts`
- [ ] Sur le serveur The Eye : `Enter-PSSession` fonctionne
- [ ] Dans The Eye : la machine est ajoutée avec `DOMAINE\Compte` ou `MACHINE\Compte`
