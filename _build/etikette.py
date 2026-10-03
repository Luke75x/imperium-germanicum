"""Inhalte des Etiketten-Guides (wortgetreu aus der bisherigen Website übernommen)."""

PRAEAMBEL = [
    "Diese Etikette ist im gesamten Reichsgebiet allgemein gültig und wirksam, alle Untertanen und Titelträger müssen sich an diese Regeln halten.",
    "Die Etikette beinhaltet zum einen die korrekte Anrede verschiedener Positionen und Titel in der direkten Absprache, in dritter Person, männlich und weiblich, Briefanschrift, als auch allgemeine Verhaltensregeln zu den Titeln.",
    "Des Weiteren werden hier Regeln festgelegt die unabhängig davon welcher Titel gerade vor Ort ist immer Anwendung finden.",
    "Die Titel werden unterteilt in Adelstitel, also solche die durch Erbschaft oder Verleihung erworben werden können, Amtstitel, welche positionsbedingt, durch eine Wahl oder mit einer speziellen zusätzlichen Aufgabe verbunden sind und Kirchentitel, die vom Heiligen Stuhl aus verliehen werden.",
    "Die Titel sind immer sortiert vom Ranghöchsten zum Rangniedrigsten, am Ende der Etikette werden alle Titel, also Adels- und Amtstitel, nochmals nach Rangfolge aufgelistet.",
]

# Jede Zeile: (Bezeichnung, männlich, weiblich) – None, wenn im Original nicht angegeben.
BOW_RULE = ("Beim Verbeugen oder Knicksen gelten folgende Regeln, alle niedrigeren Titelträger oder Untertanen haben sich zu "
            "verbeugen, es sei denn es handelt sich um einen Gleichrangigen, Kurfürst oder Fürstbischof.")


def standard(direct_m, direct_w, third_m, third_w, brief_m, brief_w):
    return [
        ("Anrede direkt", direct_m, direct_w),
        ("Anrede dritte Person", third_m, third_w),
        ("Anrede Briefkopf", brief_m, brief_w),
    ]


GRUPPEN = [
    {
        "id": "amtstitel",
        "name": "Amtstitel",
        "titel": [
            {
                "name": "Kaiser/Kaiserin",
                "anrede": standard(
                    "Eure (kaiserliche und königliche) Majestät", "Eure (kaiserliche und königliche) Majestät",
                    "Seine (kaiserliche und königliche) Majestät", "Ihre (kaiserliche und königliche) Majestät",
                    "SKKM", "IKKM"),
                "bemerkung": [
                    "Der Kaiser oder die Kaiserin, allgemein als der Souverän oder Imperator und Imperatrix bezeichnet, ist die höchste Position des Reiches und genießt als solche die höchste Autorität.",
                    "Allgemein gilt, dass bei der ersten Begrüßung und der Verabschiedung sowohl die lange Variante mit dem Zusatz kaiserlich und königlich, als auch das geläufige kurze Eure Majestät zulässig sind.",
                    "Im allgemeinen Verlauf des Gesprächs ist ein einfaches Majestät gestattet, es dürfen aber auch die längeren Versionen genutzt werden.",
                    "Der Souverän ist die einzige Person im Reich vor der sich alle anderen Titel bei erster Begrüßung und Verabschiedung leicht, aber mit Würde, zu verneigen haben, beziehungsweise einen Knicks zu machen haben.",
                ],
            },
            {
                "name": "Reichsombudsmann/Reichsombudsfrau",
                "zusatz": "(Hand des Kaisers)",
                "anrede": standard(
                    "Eure (kaiserliche und königliche) Hoheit", "Eure (kaiserliche und königliche) Hoheit",
                    "Seine (kaiserliche und königliche) Hoheit", "Ihre (kaiserliche und königliche) Hoheit",
                    "SKKH", "IKKH"),
                "bemerkung": [
                    "Der Reichsombudsmann oder Reichsombudsfrau, allgemein als Hand des Kaisers bezeichnet, ist die zweithöchste Position des Reiches und genießt als solche sehr hohe Autorität.",
                    "Im allgemeinen Verlauf des Gesprächs ist ein einfaches kaiserlich königliche Hoheit gestattet, es darf aber auch die längere Version genutzt werden.",
                    "Die Hand des Kaisers kann in bestimmten Situationen stellvertretend für den Souverän tätig sein, in diesen Situationen gelten die gleichen Regeln in Bezug auf das Verneigen wie beim Souverän.",
                ],
            },
            {
                "name": "Kurfürst/Kurfürstin",
                "anrede": standard(
                    "Eure königliche Hoheit", "Eure königliche Hoheit",
                    "Seine königliche Hoheit", "Ihre königliche Hoheit",
                    "SKH", "IKH"),
                "bemerkung": [
                    "Der Kurfürst oder die Kurfürstin sind ein Amt, von dem es maximal 9 gleichzeitig geben kann, sie bilden zusammen mit der Hand des Kaisers den Senat und wählen den Souverän.",
                    "Im allgemeinen Verlauf des Gesprächs ist ein einfaches königliche Hoheit gestattet, es darf aber auch die längere Version genutzt werden.",
                    "Die Kurfürsten genießen eine hohe Autorität, verbeugen oder knicksen müssen vor ihnen alle Untertanen ihres Herrschaftsgebiets und alle niedrigeren Titelträger im Reich, ausgenommen hiervon sind andere Kurfürsten, Fürstbischof, Gleichrangige und Träger eines höheren Adelstitels welche aber keine Kurfürsten sind.",
                ],
            },
            {
                "name": "Fürstbischof",
                "anrede": standard("Eure Exzellenz", None, "Seine Exzellenz", None, "SE", None),
                "bemerkung": [
                    "Die Fürstbischöfe sind ein Amt, welches genau genommen gleichzusetzen mit einem normalen Fürsten ist, manche von ihnen die auch Kurwürde besitzen bilden also zusammen mit den anderen Kurfürsten und der Hand des Kaisers den Senat und wählen den Souverän.",
                    "Im allgemeinen Verlauf des Gesprächs ist ein einfaches Exzellenz gestattet, es darf aber auch die längere Version genutzt werden.",
                    "Der Fürstbischof genießt eine hohe Autorität, verbeugen oder knicksen müssen vor ihm alle Untertanen seines Herrschaftsgebiets und alle niedrigeren Titelträger im Reich, ausgenommen hiervon sind andere Kurfürsten, Gleichrangige und Träger eines höheren Adelstitels welche aber keine Kurfürsten sind.",
                ],
            },
            {
                "name": "Oberster Reichsrichter/Oberste Reichsrichterin",
                "anrede": standard(
                    "Euer höchst Ehren", "Euer höchst Ehren",
                    "Seine höchst Ehren", "Ihre höchst Ehren",
                    "ShE", "IhE"),
                "bemerkung": [
                    "Der Oberste Reichsrichter oder die Oberste Reichsrichterin ist der höchste Richter des Reiches und als solcher Chef der Judikative.",
                    "Im allgemeinen Verlauf des Gesprächs ist ein einfaches Euer Ehren gestattet, es darf aber auch die längere Version genutzt werden.",
                    "Im Gericht genießt der Oberste unter den Reichsrichtern die höchste Autorität, Mitglieder des Gerichtes haben sich stets zu verbeugen oder zu knicksen, das Selbige gilt für den Kläger und Angeklagten.",
                ],
            },
            {
                "name": "Vizekönig/Generalgouverneur/Gouverneur",
                "anrede": standard(
                    "Eure Exzellenz", "Eure Exzellenz",
                    "Seine Exzellenz", "Ihre Exzellenz",
                    "SE", "IE"),
                "bemerkung": [
                    "Die vizeköniglichen Vertreter sind Beamte, welche vom Souverän direkt mit der Verwaltung eines Gebietes betraut sind.",
                    "Innerhalb ihres Territoriums vertreten sie den Souverän direkt und übernehmen in dessen Namen seine Aufgaben.",
                    "Daher genießen sie in der Zeit der Abwesenheit des Souveräns die Würde der Krone.",
                ],
            },
            {
                "name": "Sprecher des Reichstages/Sprecherin des Reichstages",
                "anrede": [
                    ("Anrede direkt", "Herr Sprecher", "Frau Sprecherin"),
                    ("Anrede Briefkopf", "Sehr geehrter Herr Sprecher", "Sehr geehrte Frau Sprecherin"),
                ],
                "bemerkung": [
                    "Der Sprecher oder die Sprecherin des Reichstages leiten dessen Sitzungen und haben den Vorsitz, ihre Würde gilt nur in Ausübung ihres Amtes im Plenum, ansonsten sind die privaten Titel zu nutzen.",
                ],
            },
            {
                "name": "Militärische Ämter",
                "anrede": [
                    ("Anrede direkt", "Herr (Titel) (Dienstgrad)", "Frau (Titel) (Dienstgrad)"),
                    ("Anrede Briefkopf", "Sehr geehrter Herr (Titel) (Dienstgrad)", "Sehr geehrte Frau (Titel) (Dienstgrad)"),
                ],
                "bemerkung": [
                    "Militärische Dienstgrade haben einen hohen Stellenwert innerhalb des Reiches, Träger militärischer Ämter sind immer als solche anzusprechen.",
                ],
            },
        ],
    },
    {
        "id": "adelstitel",
        "name": "Adelstitel",
        "titel": [
            {
                "name": "König/Königin",
                "anrede": standard(
                    "Eure (königliche) Majestät", "Eure (königliche) Majestät",
                    "Seine (königliche) Majestät", "Ihre (königliche) Majestät",
                    "SKM", "IKM"),
                "bemerkung": [
                    "König oder Königin ist der höchste Adelstitel, sie sind mit einer besonderen Würde zu behandeln.",
                    "Allgemein gilt, dass bei der ersten Begrüßung und der Verabschiedung sowohl die lange Variante mit dem Zusatz königlich, als auch das geläufige kurze Eure Majestät zulässig sind.",
                    "Im allgemeinen Verlauf des Gesprächs ist ein einfaches Majestät gestattet, es dürfen aber auch die längeren Versionen genutzt werden.",
                    BOW_RULE,
                ],
            },
            {
                "name": "Erzherzog/Erzherzogin",
                "anrede": standard(
                    "Eure (kaiserliche und königliche) Hoheit", "Eure (kaiserliche und königliche) Hoheit",
                    "Seine (kaiserliche und königliche) Hoheit", "Ihre (kaiserliche und königliche) Hoheit",
                    "SKKH", "IKKH"),
                "bemerkung": [
                    "Erzherzog oder Erzherzogin sind hohe und würdevolle Adelstitel, sie sind mit dem nötigen Respekt zu achten.",
                    "Im allgemeinen Verlauf des Gesprächs ist ein einfaches kaiserlich königliche Hoheit gestattet, es dürfen aber auch die längeren Versionen genutzt werden.",
                    BOW_RULE,
                ],
            },
            {
                "name": "Großherzog/Großherzogin",
                "anrede": standard(
                    "Eure königliche Hoheit", "Eure königliche Hoheit",
                    "Seine königliche Hoheit", "Ihre königliche Hoheit",
                    "SKH", "IKH"),
                "bemerkung": [
                    "Großherzog oder Großherzogin sind hohe und würdevolle Adelstitel, sie sind mit dem nötigen Respekt zu achten.",
                    "Im allgemeinen Verlauf des Gesprächs ist ein einfaches königliche Hoheit gestattet, es dürfen aber auch die längeren Versionen genutzt werden.",
                    BOW_RULE,
                ],
            },
            {
                "name": "Herzog/Herzogin, Landgraf/Landgräfin, Pfalzgraf/Pfalzgräfin, Markgraf/Markgräfin",
                "anrede": standard(
                    "Eure (königliche) Hoheit", "Eure (königliche) Hoheit",
                    "Seine (königliche) Hoheit", "Ihre (königliche) Hoheit",
                    "SKH", "IKH"),
                "bemerkung": [
                    "Die oben genannten Titel von Herzog und Herzogin bis zu Markgraf und Markgräfin sind hohe und würdevolle Adelstitel, sie sind mit dem nötigen Respekt zu achten.",
                    "Im allgemeinen Verlauf des Gesprächs ist ein einfaches Hoheit gestattet, es dürfen aber auch die längeren Versionen genutzt werden.",
                    BOW_RULE,
                ],
            },
            {
                "name": "Fürst/Fürstin",
                "anrede": standard(
                    "Eure Hoheit", "Eure Hoheit",
                    "Seine Hoheit", "Ihre Hoheit",
                    "SH", "IH"),
                "bemerkung": [
                    "Fürst und Fürstin sind mittelhohe und würdevolle Adelstitel, sie sind mit dem nötigen Respekt zu achten.",
                    "Im allgemeinen Verlauf des Gesprächs ist ein einfaches Hoheit gestattet, es dürfen aber auch die längeren Versionen genutzt werden.",
                    BOW_RULE,
                ],
            },
            {
                "name": "Graf/Gräfin",
                "anrede": standard(
                    "Erlaucht", "Erlaucht",
                    "Seine Erlaucht", "Ihre Erlaucht",
                    "SE", "IE"),
                "bemerkung": [
                    "Graf und Gräfin sind würdevolle Adelstitel, sie sind mit dem nötigen Respekt zu achten.",
                    "Im allgemeinen Verlauf des Gesprächs ist ein einfaches Erlaucht gestattet.",
                    BOW_RULE,
                ],
            },
            {
                "name": "Baron/Baronin",
                "anrede": standard(
                    "Hochwohlgeboren", "Hochwohlgeboren",
                    "Seine Hochwohlgeboren", "Ihre Hochwohlgeboren",
                    "SHw", "IHw"),
                "bemerkung": [
                    "Baron und Baronin sind würdevolle Adelstitel, sie sind mit dem nötigen Respekt zu achten.",
                    "Im allgemeinen Verlauf des Gesprächs ist ein einfaches Hochwohlgeboren gestattet, es dürfen aber auch die längeren Versionen genutzt werden.",
                    BOW_RULE,
                ],
            },
        ],
    },
    {
        "id": "kirchentitel",
        "name": "Kirchentitel",
        "titel": [
            {
                "name": "Papst",
                "anrede": standard("Eure Heiligkeit/Heiliger Vater", None, "Seine Heiligkeit/Heiliger Vater", None, "SH", None),
                "bemerkung": [
                    "Der Papst ist als Bischof von Rom und Pontifex Maximus das Oberhaupt der katholischen Kirche und Vertreter Christi auf Erden, als solcher ist er immer mit den höchsten zeremoniellen Ehren zu begrüßen.",
                ],
            },
            {
                "name": "Kardinalstaatssekretär/Kardinal",
                "anrede": standard("Eure Eminenz", None, "Seine Eminenz", None, "SEm", None),
                "bemerkung": [
                    "Kardinäle sind nach dem Papst die höchsten Würdenträger der katholischen Kirche, einer der Kardinäle ist als Kardinalstaatssekretär der Regierungschef des Heiligen Stuhls.",
                    "Kardinäle sind stets mit höchster Würde zu empfangen.",
                ],
            },
            {
                "name": "Erzbischof/Bischof/Weihbischof",
                "anrede": standard("Eure Exzellenz", None, "Seine Exzellenz", None, "SE", None),
                "bemerkung": [
                    "Bischöfe sind als Kirchenfürsten und Vertreter des Heiligen Stuhls stets mit höchsten Würden zu begrüßen, sie repräsentieren den Heiligen Stuhl lokal in ihrem Bistum.",
                ],
            },
        ],
    },
]

VERHALTENSREGELN = [
    "Allgemein gilt, dass die Person mit dem höheren Rang immer das Vorrecht hat, sind zwei Personen im gleichen Rang, so ist der dienstälteste vorrangig.",
    "Dieses Leitbild zieht sich durch alle anderen Regeln durch, bei Tisch gilt also, dass der mit dem höchsten Rang zuerst Platz nimmt und auch als erster mit dem Essen beginnt.",
    "In genau dieser Reihenfolge wird sich auch zu Fuß bewegt, zum Beispiel beim Flanieren.",
    "Die Person mit dem höheren Rang begrüßt jene mit dem niedrigeren Rang, danach erfolgt die Begrüßung zurück und erst dann beginnt das Gespräch.",
]

RANGLISTE_HINWEIS = ("(Vereinfacht, in männlicher Form) Es gilt außerdem, dass der Gatte oder die Gattin nach diesem "
                     "Protokoll immer direkt im Rang folgt und dann erst der nächste Titel folgt.")

RANGLISTE = [
    "Kaiser",
    "Papst (Bischof von Rom)",
    "Reichsombudsmann (Hand des Kaisers)",
    "Kardinalstaatssekretär",
    "König/Kurfürst/Fürstbischof mit Kurwürde",
    "Erzherzog",
    "Oberster Reichsrichter",
    "Vizekönig",
    "Generalgouverneur",
    "Gouverneur",
    "Großherzog",
    "Herzog",
    "Sprecher des Reichstages",
    "Landgraf",
    "Pfalzgraf",
    "Markgraf",
    "Fürst/Fürstbischof ohne Kurwürde",
    "Graf",
    "Baron",
    "Freiherr/Ritter",
]

RANGLISTE_SCHLUSS = ("Alle weiteren Regierungsämter und Dienstgrade von Militär und öffentlichen Einrichtungen finden "
                     "sich darunter ein, sowie Kirchentitel ohne weltliche Gewalt.")
