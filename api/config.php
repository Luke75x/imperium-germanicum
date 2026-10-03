<?php
/**
 * Konfiguration der Formularverarbeitung.
 * Diese Datei liegt nicht öffentlich abrufbar im Ordner /api (siehe .htaccess).
 */
return [
    // Empfänger aller Formularnachrichten
    'empfaenger'   => 'das.imperium.germanicum@gmail.com',

    // Absenderadresse – muss zur Domain des Webspace gehören, sonst landen Mails im Spam
    'absender'     => 'no-reply@imperiumgermanicum.de',
    'absender_name' => 'Imperium Germanicum – Website',

    // Spamschutz
    'min_sekunden' => 3,     // Mindestzeit zwischen Seitenaufruf und Absenden
    'max_pro_std'  => 5,     // Maximale Anzahl Formulare pro IP und Stunde

    // Weiterleitungsziele für Besucher ohne JavaScript (relativ zum Website-Stamm)
    'danke' => [
        'kontakt'  => '/kontakt/danke/',
        'widerruf' => '/widerruf/danke/',
    ],
    'fehler' => [
        'kontakt'  => '/kontakt/?fehler=1',
        'widerruf' => '/widerruf/?fehler=1',
    ],
];
