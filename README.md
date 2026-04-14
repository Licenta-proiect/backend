# 📘 USV Recovery Manager - Backend API

Acesta este nucleul computațional al sistemului de gestionare a recuperărilor didactice din cadrul **Facultății de Inginerie Electrică și Știința Calculatoarelor (FIESC)**. Sistemul automatizează identificarea sloturilor libere, procesul de rezervare a sălilor și sincronizarea cu orarul oficial, asigurând integritatea datelor și securitatea utilizatorilor.

---

## 🚀 Tehnologii și Biblioteci Utilizate

Alegerea stack-ului tehnologic a fost dictată de necesitatea unei performanțe ridicate, a siguranței datelor și a suportului pentru procesare asincronă:

* **FastAPI:** Ales pentru viteza superioară de execuție (bazat pe Starlette și Pydantic), suportul nativ pentru `async/await` și generarea automată a documentației interactive (Swagger/OpenAPI).
* **SQLAlchemy (ORM):** Utilizat pentru maparea obiect-relațională, permițând interacțiunea cu baza de date într-un mod securizat și eliminând riscul de SQL Injection.
* **PostgreSQL:** Sistemul de gestiune a bazelor de date relaționale ales pentru robustețe, suportul excelent pentru tranzacții complexe și consistența datelor.
* **Google OR-Tools:** Bibliotecă de optimizare avansată utilizată pentru rezolvarea problemelor de tip *Constraint Programming* (identificarea sloturilor libere prin solver-ul CP-SAT).
* **Google OAuth2 & JWT:** Autentificare instituțională securizată combinată cu JSON Web Tokens (`python-jose`) pentru gestionarea sesiunilor.
* **APScheduler:** Utilizat pentru automatizarea task-urilor de fundal (*cron jobs*), cum ar fi backup-urile automate și sincronizarea periodică a orarului.
* **Bleach & BeautifulSoup4:** Folosite pentru extragerea (*scraping*) și sanitizarea datelor provenite de pe serverele oficiale (`orar.usv.ro`), prevenind atacurile de tip XSS.

---

## 🏗️ Arhitectura Sistemului

Aplicația urmează un model modular de tip **Layered Architecture** (Arhitectură pe straturi):

| Director | Responsabilitate |
| :--- | :--- |
| `app/routers/` | Definește punctele de acces (endpoints) ale API-ului și logica de rutare. |
| `app/services/` | **Creierul aplicației.** Conține logica de business, algoritmii de optimizare, serviciile de email și procesele de scraping. |
| `app/models/` | Definirea structurii bazei de date (tabele, relații, constrângeri) folosind SQLAlchemy. |
| `app/schemas/` | Modele Pydantic pentru validarea și serializarea datelor de intrare/ieșire. |
| `app/db/` | Configurarea sesiunilor și a conexiunii cu motorul PostgreSQL. |
| `app/utils/` | Funcții utilitare pentru gestionarea timpului, datelor calendaristice și a configurațiilor. |

---

## 🗄️ Modelul de Date (Baza de Date)

Schema reflectă ierarhia universitară și fluxul de lucru pentru recuperări:

### 1. Entități Academice
* `Faculty`, `Specialization`, `Year`, `Group`, `Subgroup`, `Room`, `Professor`.

### 2. Logica de Orar
* **Schedule:** Stochează datele statice preluate prin scraping din orarul oficial al facultății.
* **Reservation:** Gestionează cererile de recuperare (status: *pending, approved, rejected*), incluzând relații cu profesorii adiționali și subgrupele vizate.

### 3. Sistem și Audit
* **User:** Gestionează conturile cu roluri de `ADMIN`, `PROFESSOR` sau `STUDENT`.
* **SyncHistory & DatabaseBackup:** Jurnalizarea proceselor de sincronizare și a stării backup-urilor.
* **SystemStatus:** Tabel de configurare globală pentru monitorizarea mentenanței și a intervalelor de sincronizare.

---

## 🔐 Autentificare și Securitate (2FA)

Sistemul implementează un flux de securitate riguros, în două etape:

1.  **Google Login:** Utilizatorii se autentifică folosind contul instituțional (`@student.usv.ro` sau email de profesor).
2.  **Two-Factor Authentication (2FA):** Pentru rolurile cu privilegii ridicate (Admin și Profesor), după logarea cu Google, sistemul generează un **cod OTP de 6 cifre** valid timp de 5 minute, trimis prin email (SMTP).
3.  **Autorizare:** Accesul final la rutele protejate este permis doar după validarea acestui cod, moment în care se emite token-ul JWT final.

---

## 📡 Servicii și Logică de Business

### 1. Identificarea Sloturilor Libere (Solver CP-SAT)
Inima aplicației utilizează **Google OR-Tools** pentru a găsi intervale libere prin intersectarea:
* Orarului oficial al profesorului și al grupei.
* Rezervărilor deja existente și aprobate în sistem.
* Disponibilității sălii selectate, ținând cont de configurația săptămânilor (par/impar).

### 2. Sincronizarea Datelor (Web Scraping)
* app/services/scraper.py: Descarcă datele JSON oficiale. Include logică de "smart merge" pentru profesori: dacă un profesor are deja cont activ, email-ul său nu este suprascris de scraper pentru a nu întrerupe accesul.

* Sanitizare: Utilizăm bleach pentru a curăța orice input provenit din scraping, protejând baza de date împotriva atacurilor de tip XSS injectate în sursele externe.

### 3. Managementul Backup-ului
Sistemul realizează backup-uri automate (`pg_dump`) și le încarcă securizat în **Google Drive**, asigurând recuperarea datelor în caz de incident.

---

## 🛣️ Rute API Principale

* `/auth`: Gestiune Login Google, verificare cod 2FA și solicitări de acces.
* `/admin`: Management utilizatori, control scraping și configurare backup.
* `/professors`: Vizualizarea orarului personal și managementul cererilor.
* `/reservation`: Căutare inteligentă a sloturilor libere și confirmarea rezervărilor.
* `/data`: Endpoints pentru popularea listelor (facultăți, grupe, săli).