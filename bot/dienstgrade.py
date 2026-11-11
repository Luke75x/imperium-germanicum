"""Dienstgradstrukturen des Imperiums (Stand 03.11.2026).

Quelle: Beschluss „Imperium Germanicum – Dienstgrade“ (Tabelle im Reichsgesetzblatt, Thread 1562936706318209106) und die Discord-Rollen
„OF-n …“/„OR-n …“. Je Institution stehen die Dienstgrade von unten nach oben als (Stufe, Bezeichnung, Rollen-ID). Die Stufe folgt der
Tabelle; sie ist Grundlage für die Genehmigungsgrenze (ab OF-6 entscheidet der Kaiser). Heer, Luftwaffe und Reichssicherheitsamt teilen
sich dieselben Rollen. Nicht enthalten: Inquisition (die Justiz-Dienstgrade der Tabelle haben keine Discord-Rollen) und Ämter wie
Stabschef oder Generaldirektor (das sind Positionen, keine Dienstgrade).
Reichsverwaltung: Beamtenlaufbahn nach der Reihenfolge der Discord-Rollen (Amtsmann … Generaldirektor), Stufe „RV“; die Regionalämter
Vizekönig … Bürgermeister sind Ämter der Regenten und gehören nicht dazu.
"""

INSTITUTIONEN = {
    "marine": ("Kaiserliche Marine", 1526343421386690663),
    "heer": ("Kaiserliches Heer", 1526343002966986882),
    "luftwaffe": ("Kaiserliche Luftwaffe", 1526343128997695528),
    "krs": ("Kaiserliches Reichssicherheitsamt", 1526343577481904379),
    "polizei": ("Kaiserliche Polizeibehörde", 1557800373861753002),
    "zoll": ("Kaiserliche Zollverwaltung", 1557187375006875758),
    "kks": ("Kaiserlicher Katastrophenschutz", 1557187293100515328),
    "reichsverwaltung": ("Reichsverwaltung", 1526348059984789504),
}
ZIVIL = {"reichsverwaltung"}      # Beamtenlaufbahn: keine Stufen OF/OR, keine Sammelrolle „Abteilungen“, keine Gruppenrollen
NUR_KANZLER = {"reichsverwaltung"}  # einstellen darf nur der Kronkanzler (oder der Kaiser), sonst jeder Landesherr
SAMMELROLLE_ABTEILUNGEN = 1526342856438972556     # Rolle „Abteilungen“, kommt mit jeder Institutionsrolle
GRUPPENROLLEN = {"mannschaften": 1522921421398081689, "unteroffiziere": 1522917239769141428,
                 "offiziere": 1522914146390380636, "generalstab": 1522706926973096057}
KAISER_AB = 6      # OF-6 und höher: Genehmigung des Kaisers

RAENGE = {'marine': [('OR-1', 'Matrose', '1522923137900085288'),
            ('OR-1', 'Matrosengefreiter', '1522922949533765722'),
            ('OR-2', 'Matrosenobergefreiter', '1522922651234865222'),
            ('OR-3', 'Matrosenhauptgefreiter', '1522922320115531940'),
            ('OR-4', 'Matrosenstabsgefreiter', '1522922104129851444'),
            ('OR-4', 'Matrosenoberstabsgefreiter', '1522921578768109700'),
            ('OR-5', 'Maat', '1522919946202386512'),
            ('OR-6', 'Obermaat', '1522919691067064450'),
            ('OR-7', 'Bootsmann', '1522919270592282814'),
            ('OR-8', 'Oberbootsmann', '1522918605979648080'),
            ('OR-9', 'Stabsbootsmann', '1522919106737606748'),
            ('OR-9', 'Stabsoberbootsmann', '1522918372247994469'),
            ('OF-1', 'Leutnant zur See', '1522917009518493778'),
            ('OF-1', 'Oberleutnant zur See', '1522916833227964529'),
            ('OF-2', 'Kapitänleutnant', '1522916637487927316'),
            ('OF-3', 'Korvettenkapitän', '1522916069843538090'),
            ('OF-4', 'Fregattenkapitän', '1522915819393253546'),
            ('OF-5', 'Kapitän zur See', '1522915240155680908'),
            ('OF-5', 'Kommodore', '1522914757001347162'),
            ('OF-6', 'Konteradmiral', '1522717359209582682'),
            ('OF-7', 'Vizeadmiral', '1522709628255731852'),
            ('OF-8', 'Admiral', '1522709153385025577'),
            ('OF-9', 'Flottenadmiral', '1522708853580497156'),
            ('OF-10', 'Großadmiral', '1522707936181489715'),
            ('OF-11', 'Großmarschall', '1522707842832929020')],
 'heer': [('OR-1', 'Soldat', '1522923188831391876'),
          ('OR-1', 'Obersoldat', '1522923068115124314'),
          ('OR-2', 'Gefreiter', '1522922764795777116'),
          ('OR-3', 'Obergefreiter', '1522922504044150866'),
          ('OR-4', 'Stabsgefreiter', '1522922185780367480'),
          ('OR-4', 'Oberstabsgefreiter', '1522921898672128050'),
          ('OR-5', 'Unteroffizier', '1522927457320042546'),
          ('OR-6', 'Unterfeldwebel', '1522919779206430810'),
          ('OR-7', 'Feldwebel', '1522919339236397187'),
          ('OR-8', 'Oberfeldwebel', '1522919196260958238'),
          ('OR-9', 'Stabsfeldwebel', '1522919025321971742'),
          ('OF-1', 'Leutnant', '1522917068700254318'),
          ('OF-1', 'Oberleutnant', '1522916891520270506'),
          ('OF-2', 'Hauptmann', '1522916696216703007'),
          ('OF-3', 'Major', '1522916118027571310'),
          ('OF-4', 'Oberstleutnant', '1522915927027482774'),
          ('OF-5', 'Oberst', '1522915462273306735'),
          ('OF-5', 'Brigadeoberst', '1522914856964063397'),
          ('OF-6', 'Generalmajor', '1522720162480914492'),
          ('OF-7', 'Generalleutnant', '1522709789518463097'),
          ('OF-8', 'General der Waffengattung', '1522709250219053158'),
          ('OF-9', 'Generaloberst', '1522709057490653376'),
          ('OF-10', 'Generalfeldmarschall', '1522708024010080317')],
 'luftwaffe': [('OR-1', 'Soldat / Flieger', '1522923188831391876'),
               ('OR-1', 'Oberflieger', '1522923068115124314'),
               ('OR-2', 'Gefreiter', '1522922764795777116'),
               ('OR-3', 'Obergefreiter', '1522922504044150866'),
               ('OR-4', 'Stabsgefreiter', '1522922185780367480'),
               ('OR-4', 'Oberstabsgefreiter', '1522921898672128050'),
               ('OR-5', 'Unteroffizier', '1522927457320042546'),
               ('OR-6', 'Unterfeldwebel', '1522919779206430810'),
               ('OR-7', 'Feldwebel', '1522919339236397187'),
               ('OR-8', 'Oberfeldwebel', '1522919196260958238'),
               ('OR-9', 'Stabsfeldwebel', '1522919025321971742'),
               ('OF-1', 'Leutnant', '1522917068700254318'),
               ('OF-1', 'Oberleutnant', '1522916891520270506'),
               ('OF-2', 'Hauptmann', '1522916696216703007'),
               ('OF-3', 'Major', '1522916118027571310'),
               ('OF-4', 'Oberstleutnant', '1522915927027482774'),
               ('OF-5', 'Oberst', '1522915462273306735'),
               ('OF-6', 'Generalmajor', '1522720162480914492'),
               ('OF-7', 'Generalleutnant', '1522709789518463097'),
               ('OF-8', 'General der Waffengattung', '1522709250219053158'),
               ('OF-9', 'Generaloberst', '1522709057490653376'),
               ('OF-10', 'Generalfeldmarschall', '1522708024010080317')],
 'krs': [('OR-1', 'Soldat', '1522923188831391876'),
         ('OR-1', 'Obersoldat', '1522923068115124314'),
         ('OR-2', 'Gefreiter', '1522922764795777116'),
         ('OR-3', 'Obergefreiter', '1522922504044150866'),
         ('OR-4', 'Stabsgefreiter', '1522922185780367480'),
         ('OR-4', 'Oberstabsgefreiter', '1522921898672128050'),
         ('OR-5', 'Unteroffizier', '1522927457320042546'),
         ('OR-6', 'Unterfeldwebel', '1522919779206430810'),
         ('OR-7', 'Feldwebel', '1522919339236397187'),
         ('OR-8', 'Oberfeldwebel', '1522919196260958238'),
         ('OR-9', 'Stabsfeldwebel', '1522919025321971742'),
         ('OF-1', 'Leutnant', '1522917068700254318'),
         ('OF-1', 'Oberleutnant', '1522916891520270506'),
         ('OF-2', 'Hauptmann', '1522916696216703007'),
         ('OF-3', 'Major', '1522916118027571310'),
         ('OF-4', 'Oberstleutnant', '1522915927027482774'),
         ('OF-5', 'Oberst', '1522915462273306735'),
         ('OF-5', 'Brigadeoberst', '1522914856964063397'),
         ('OF-6', 'Generalmajor', '1522720162480914492'),
         ('OF-7', 'Generalleutnant', '1522709789518463097'),
         ('OF-8', 'General der Waffengattung', '1522709250219053158'),
         ('OF-9', 'Generaloberst', '1522709057490653376'),
         ('OF-10', 'Generalfeldmarschall', '1522708024010080317')],
 'polizei': [('OR-1', 'Polizeiwachtmeister', '1557354556558417990'),
             ('OR-1', 'Polizeioberwachtmeister', '1557354694463062066'),
             ('OR-2', 'Polizeihauptwachtmeister', '1557355003528740956'),
             ('OR-3', 'Erster Polizeihauptwachtmeister', '1557355093979045988'),
             ('OR-4', 'Erster Polizeihauptwachtmeister m.Z.', '1557355175893663874'),
             ('OR-5', 'Polizeimeister', '1557344593794830346'),
             ('OR-6', 'Polizeiobermeister', '1557344482901630976'),
             ('OR-7', 'Polizeihauptmeister', '1557344388362014830'),
             ('OR-8', 'Polizeihauptmeister m.Z.', '1557344322381283359'),
             ('OF-1', 'Polizeikommissar', '1557334659409379368'),
             ('OF-1', 'Polizeioberkommissar', '1557334593894486086'),
             ('OF-2', 'Polizeihauptkommissar', '1557334514315821176'),
             ('OF-3', 'Polizeihauptkommissar m.Z.', '1557334462595997747'),
             ('OF-4', 'Erster Polizeihauptkommissar', '1557334319905898556'),
             ('OF-5', 'Erster Polizeihauptkommissar m.Z.', '1557334261948883035'),
             ('OF-6', 'Polizeirat', '1557190268770459698'),
             ('OF-7', 'Polizeioberrat', '1557190089350709298'),
             ('OF-8', 'Polizeidirektor', '1557189964108664902'),
             ('OF-9', 'Leitender Polizeidirektor', '1557189875164385290')],
 'zoll': [('OR-1', 'Zollwachtmeister', '1557186634779459614'),
          ('OR-1', 'Zolloberwachtmeister', '1557186567607427212'),
          ('OR-2', 'Zollhauptwachtmeister', '1557186500557537290'),
          ('OR-3', 'Erster Zollhauptwachtmeister', '1557186393791533096'),
          ('OR-4', 'Erster Zollhauptwachtmeister m.Z.', '1557186336216055858'),
          ('OR-5', 'Zollsekretär', '1557185510181707908'),
          ('OR-6', 'Zollobersekretär', '1557185441759895593'),
          ('OR-7', 'Zollhauptsekretär', '1557185373300465704'),
          ('OR-8', 'Zollamtsinspektor', '1557185167884296212'),
          ('OR-9', 'Zollamtsinspektor m.Z.', '1557185042806210580'),
          ('OF-1', 'Zollinspektor', '1557183846586253422'),
          ('OF-1', 'Zolloberinspektor', '1557183755028799591'),
          ('OF-2', 'Zollamtmann', '1557183671264608276'),
          ('OF-3', 'Zollamtsrat', '1557183584270290954'),
          ('OF-4', 'Zolloberamtsrat', '1557183448886804581'),
          ('OF-5', 'Zolloberamtsrat m.Z.', '1557183350572195900'),
          ('OF-6', 'Regierungsrat', '1557182671505850499'),
          ('OF-7', 'Oberregierungsrat', '1557182598487343124'),
          ('OF-8', 'Regierungsdirektor', '1557182483580325989'),
          ('OF-9', 'Leitender Regierungsdirektor', '1557180854235693128')],
 'kks': [('OR-1', 'Schutzmann', '1557178967595810816'),
         ('OR-1', 'Oberschutzmann', '1557178867020464138'),
         ('OR-2', 'Schutzmeister', '1557178754520973322'),
         ('OR-3', 'Oberschutzmeister', '1557178672815931412'),
         ('OR-4', 'Hauptschutzmeister', '1557178599759417434'),
         ('OR-5', 'Schutzmeister Gf.', '1557177367200403496'),
         ('OR-6', 'Oberschutzmeister Gf.', '1557177256923889694'),
         ('OR-7', 'Hauptschutzmeister Gf.', '1557177146370293800'),
         ('OR-8', 'Hauptschutzmeister m.Z.', '1557177059045023776'),
         ('OF-1', 'Schutzinspektor', '1557175459991658537'),
         ('OF-1', 'Schutzoberinspektor', '1557175275115122730'),
         ('OF-2', 'Schutzamtmann', '1557174998362366043'),
         ('OF-3', 'Schutzamtsrat', '1557174876022902814'),
         ('OF-4', 'Schutzoberamtsrat', '1557174751565320302'),
         ('OF-6', 'Schutzrat', '1557172772222795891'),
         ('OF-7', 'Oberschutzrat', '1557172682318028891'),
         ('OF-8', 'Schutzdirektor', '1557172195254603816'),
         ('OF-9', 'Leitender Schutzdirektor', '1557171030173294613')]}

RAENGE["reichsverwaltung"] = [("RV", n, r) for n, r in (
    ("Amtsmann", 1555985042180669541), ("Amtsrat", 1555985146392617061), ("Inspektor", 1526342268691419278),
    ("Direktor", 1526341196081791076), ("Ministerialrat", 1526342162952884304), ("Ministerialdirektor", 1555985280203231322),
    ("Staatssekretär", 1526341106755960912), ("Generaldirektor", 1555972124215353445))]


def stufe_zahl(stufe: str) -> int:
    return int(stufe.split("-")[1])


def gruppe(stufe: str):
    """Dienstgradgruppe (Rollen Mannschaften/Unteroffiziere/Offiziersränge/Generalstab) zur Stufe; None bei Beamten (RV)."""
    if stufe == "RV":
        return None
    n = stufe_zahl(stufe)
    if stufe.startswith("OR"):
        return "mannschaften" if n <= 4 else "unteroffiziere"
    return "offiziere" if n <= 5 else "generalstab"


def braucht_genehmigung(stufe: str) -> bool:
    return stufe.startswith("OF") and stufe_zahl(stufe) >= KAISER_AB


def bezeichnung(schluessel: str, index: int) -> str:
    stufe, name, _ = RAENGE[schluessel][index]
    return name if stufe == "RV" else f"{stufe} {name}"
