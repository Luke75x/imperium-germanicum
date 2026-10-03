<?php
/**
 * Verarbeitung von Kontakt- und Widerrufsformular.
 *
 * - Antwortet mit JSON, wenn der Browser "Accept: application/json" sendet (JavaScript aktiv),
 *   sonst mit einer Weiterleitung auf die Danke- bzw. Fehlerseite.
 * - Spamschutz ohne Drittanbieter: Honeypot-Feld, Mindest-Ausfüllzeit, Rate-Limit pro IP (gehasht).
 */
declare(strict_types=1);

$config = require __DIR__ . '/config.php';

header('X-Content-Type-Options: nosniff');
header('Cache-Control: no-store');

$wantsJson = stripos($_SERVER['HTTP_ACCEPT'] ?? '', 'application/json') !== false;
$formular  = (string)($_POST['formular'] ?? '');

function antwort(bool $ok, string $nachricht, int $status = 200): void
{
    global $wantsJson, $config, $formular;
    if ($wantsJson) {
        http_response_code($status);
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode(['ok' => $ok, 'message' => $nachricht], JSON_UNESCAPED_UNICODE);
    } else {
        $ziele = $ok ? $config['danke'] : $config['fehler'];
        header('Location: ' . ($ziele[$formular] ?? '/'), true, 303);
    }
    exit;
}

/** Entfernt Steuerzeichen und kürzt auf eine Höchstlänge. */
function feld(string $name, int $max): string
{
    $wert = trim((string)($_POST[$name] ?? ''));
    $wert = preg_replace('/[^\P{C}\n\t]/u', '', $wert) ?? '';
    return mb_substr($wert, 0, $max);
}

/** Header-sichere Zeichenkette (keine Zeilenumbrüche → keine Header-Injection). */
function einzeilig(string $wert): string
{
    return trim(str_replace(["\r", "\n", "%0a", "%0d"], ' ', $wert));
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    header('Allow: POST');
    antwort(false, 'Nur POST-Anfragen sind erlaubt.', 405);
}

$felder = [
    'kontakt'  => ['name' => [120, true], 'email' => [200, true], 'nachricht' => [5000, true]],
    'widerruf' => ['name' => [120, true], 'vertrag' => [80, true], 'email' => [200, true],
                   'artikel' => [500, false], 'grund' => [3000, false]],
];
if (!isset($felder[$formular])) {
    antwort(false, 'Unbekanntes Formular.', 400);
}

// --- Spamschutz -------------------------------------------------------------

// 1. Honeypot: unsichtbares Feld muss leer bleiben. Bots erhalten eine scheinbare Erfolgsmeldung.
if (($_POST['website'] ?? '') !== '') {
    antwort(true, 'Vielen Dank!');
}

// 2. Mindest-Ausfüllzeit (nur wenn JavaScript den Zeitstempel gesetzt hat)
$ts = (int)($_POST['ts'] ?? 0);
if ($ts > 0 && (time() - $ts) < $config['min_sekunden']) {
    antwort(false, 'Das ging etwas zu schnell. Bitte warte einen Moment und sende das Formular erneut.', 429);
}

// 3. Rate-Limit pro IP (nur gehasht gespeichert, max. 1 Stunde)
$ipHash   = hash('sha256', ($_SERVER['REMOTE_ADDR'] ?? '') . __FILE__);
$limitDir = sys_get_temp_dir() . '/ig-formular';
if (!is_dir($limitDir)) {
    @mkdir($limitDir, 0700, true);
}
$limitDatei = $limitDir . '/' . $ipHash;
$jetzt      = time();
$eintraege  = [];
if (is_file($limitDatei)) {
    $eintraege = array_filter(
        array_map('intval', explode(',', (string)file_get_contents($limitDatei))),
        static fn(int $t): bool => $t > $jetzt - 3600
    );
}
if (count($eintraege) >= $config['max_pro_std']) {
    antwort(false, 'Zu viele Anfragen. Bitte versuche es später erneut oder schreibe uns direkt per E-Mail.', 429);
}

// --- Validierung ------------------------------------------------------------

$daten = [];
foreach ($felder[$formular] as $name => [$max, $pflicht]) {
    $daten[$name] = feld($name, $max);
    if ($pflicht && $daten[$name] === '') {
        antwort(false, 'Bitte fülle alle mit * gekennzeichneten Felder aus.', 422);
    }
}
$email = einzeilig($daten['email']);
if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
    antwort(false, 'Bitte gib eine gültige E-Mail-Adresse ein.', 422);
}
$name = einzeilig($daten['name']);

// --- Versand ----------------------------------------------------------------

function sende(string $an, string $betreff, string $text, string $replyTo, array $config): bool
{
    $absender = einzeilig($config['absender']);
    $kopf = [
        'From: =?UTF-8?B?' . base64_encode($config['absender_name']) . '?= <' . $absender . '>',
        'Reply-To: ' . $replyTo,
        'MIME-Version: 1.0',
        'Content-Type: text/plain; charset=UTF-8',
        'Content-Transfer-Encoding: 8bit',
        'X-Mailer: Imperium-Germanicum-Website',
    ];
    $betreff = '=?UTF-8?B?' . base64_encode($betreff) . '?=';
    return mail($an, $betreff, $text, implode("\r\n", $kopf), '-f' . $absender);
}

$zeit = date('d.m.Y H:i');
if ($formular === 'kontakt') {
    $betreff = 'Kontaktformular: Nachricht von ' . $name;
    $text = "Neue Nachricht über das Kontaktformular ({$zeit})\n\n"
          . "Name:   {$name}\n"
          . "E-Mail: {$email}\n\n"
          . "Nachricht:\n{$daten['nachricht']}\n";
    $erfolg = 'Vielen Dank für deine Nachricht! Wir melden uns so bald wie möglich bei dir.';
} else {
    $betreff = 'Widerruf: Vertrag ' . einzeilig($daten['vertrag']) . ' von ' . $name;
    $text = "Eingang eines Widerrufs ({$zeit})\n\n"
          . "Name:                 {$name}\n"
          . "E-Mail:               {$email}\n"
          . "Bestell-/Buchungsnr.: {$daten['vertrag']}\n"
          . "Artikel:              " . ($daten['artikel'] !== '' ? $daten['artikel'] : 'gesamter Vertrag') . "\n\n"
          . "Grund:\n" . ($daten['grund'] !== '' ? $daten['grund'] : '(keine Angabe)') . "\n";
    $erfolg = 'Widerruf eingegangen. Eine Eingangsbestätigung wurde an deine E-Mail-Adresse gesendet.';
}

$replyTo = '=?UTF-8?B?' . base64_encode($name) . '?= <' . $email . '>';
if (!sende($config['empfaenger'], $betreff, $text, $replyTo, $config)) {
    error_log('Formularversand fehlgeschlagen: ' . $formular);
    antwort(false, 'Die Nachricht konnte nicht gesendet werden. Bitte schreibe uns direkt an ' . $config['empfaenger'] . '.', 500);
}

if ($formular === 'widerruf') {
    $bestaetigung = "Guten Tag {$name},\n\n"
        . "hiermit bestätigen wir den Eingang Ihres Widerrufs vom {$zeit}.\n\n" . $text
        . "\nMit freundlichen Grüßen\nImperium Germanicum – Das Rollenspiel\n";
    sende($email, 'Eingangsbestätigung Ihres Widerrufs', $bestaetigung, $config['empfaenger'], $config);
}

$eintraege[] = $jetzt;
@file_put_contents($limitDatei, implode(',', $eintraege), LOCK_EX);

antwort(true, $erfolg);
