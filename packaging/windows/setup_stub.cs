// Amorce de l'installeur Windows de JARVIS Presentation Edition (Slice 07, docs/product-install.md > Installer).
//
// Compilée par `build_package.py installer` avec le compilateur C# du .NET Framework 4.x livré avec Windows
// (aucun outil à installer : recommandation sous HV-PACKAGE-10). Le paquet (dossier de la Slice 06) est zippé et
// ACCOLÉ à la fin de cet exécutable, suivi d'une remorque de 24 octets : "JVSETUP1" + position (int64) + longueur
// (int64) du zip. L'amorce ne décide rien : elle extrait le paquet à côté de la cible, puis laisse le Python DU
// PAQUET faire l'installation (`python -B -m jarvis.product_setup install`), dont elle lit la progression et l'issue.
//
// Ligne de commande (déploiement silencieux, CI, essais en dossiers simulés) :
//   /S | --silent        aucune fenêtre, aucune boîte ; code de sortie 0 = installé, 1 = échec (issue dans --result et
//                        --log), 2 = argument refusé (écrit dans --log, sinon %TEMP%\jarvis-setup-error.log),
//                        3 = installé mais JARVIS n'a pas pu être ouvert (--launch)
//   --target DIR         dossier d'installation (défaut %LOCALAPPDATA%\Programs\CIRCOE\Jarvis, LOCALAPPDATA lu dans
//                        l'environnement d'abord : un essai qui le redirige ne vise jamais le vrai profil)
//   --start-menu DIR, --desktop DIR, --no-desktop, --registry-file FILE, --result FILE, --log FILE
//                        transmis à product_setup (cibles injectables : jamais le vrai registre dans un essai)
//   --launch             ouvre JARVIS à la fin (mode silencieux)

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("JARVIS Setup")]
[assembly: System.Reflection.AssemblyCompany("CIRCOE")]
[assembly: System.Reflection.AssemblyProduct("JARVIS Presentation Edition")]

namespace Circoe.Jarvis.Setup
{
    sealed class SubStream : Stream
    {
        readonly Stream inner; readonly long start; readonly long length; long position;
        public SubStream(Stream inner, long start, long length) { this.inner = inner; this.start = start; this.length = length; }
        public override bool CanRead { get { return true; } }
        public override bool CanSeek { get { return true; } }
        public override bool CanWrite { get { return false; } }
        public override long Length { get { return length; } }
        public override long Position { get { return position; } set { position = value; } }
        public override void Flush() { }
        public override int Read(byte[] buffer, int offset, int count)
        {
            long left = length - position;
            if (left <= 0) return 0;
            if (count > left) count = (int)left;
            inner.Seek(start + position, SeekOrigin.Begin);
            int read = inner.Read(buffer, offset, count);
            position += read;
            return read;
        }
        public override long Seek(long offset, SeekOrigin origin)
        {
            long basis = origin == SeekOrigin.Begin ? 0 : origin == SeekOrigin.Current ? position : length;
            position = basis + offset;
            return position;
        }
        public override void SetLength(long value) { throw new NotSupportedException(); }
        public override void Write(byte[] buffer, int offset, int count) { throw new NotSupportedException(); }
    }

    sealed class Options
    {
        public bool Silent; public bool Launch; public string Target; public string LogFile; public string ResultFile;
        public List<string> Passthrough = new List<string>();

        public static Options Parse(string[] args)
        {
            var o = new Options();
            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i];
                if (a == "/S" || a == "--silent") o.Silent = true;
                else if (a == "--launch") o.Launch = true;
                else if (a == "--no-desktop") o.Passthrough.Add(a);
                else if ((a == "--target" || a == "--log" || a == "--result" || a == "--start-menu" || a == "--desktop" || a == "--registry-file") && i + 1 < args.Length)
                {
                    string v = Full(args[++i]);
                    if (a == "--target") o.Target = v;
                    else if (a == "--log") o.LogFile = v;
                    else if (a == "--result") o.ResultFile = v;
                    else { o.Passthrough.Add(a); o.Passthrough.Add(v); }
                }
                else throw new ArgumentException("argument inconnu : " + a);
            }
            if (o.Target == null) o.Target = DefaultTarget();
            return o;
        }

        // Chemin complet SANS séparateur final (`D:\Apps\Jarvis\` → `D:\Apps\Jarvis`) : une barre oblique inverse finale
        // avalait le guillemet fermant de la ligne de commande de Python (revue m2). Une racine (`D:\`) reste telle quelle.
        public static string Full(string value)
        {
            string full = Path.GetFullPath(value);
            string root = Path.GetPathRoot(full) ?? "";
            while (full.Length > root.Length && (full.EndsWith("\\") || full.EndsWith("/"))) full = full.Substring(0, full.Length - 1);
            return full;
        }

        // `%LOCALAPPDATA%` de l'environnement d'abord (essais en dossiers simulés, QA runtime m3), sinon le dossier connu de
        // Windows : même règle que `product_setup.default_target`.
        public static string DefaultTarget()
        {
            string local = Environment.GetEnvironmentVariable("LOCALAPPDATA");
            if (string.IsNullOrWhiteSpace(local) || !Path.IsPathRooted(local))
                local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            return Path.Combine(local, "Programs", "CIRCOE", "Jarvis");
        }

        // Mode silencieux demandé ? Lu AVANT l'analyse : un argument refusé en `/S` ne doit jamais ouvrir de boîte.
        public static bool WantsSilent(string[] args)
        {
            foreach (string a in args) if (a == "/S" || a == "--silent") return true;
            return false;
        }

        // `--log` tel que donné (même si un autre argument est refusé), pour y écrire le refus.
        public static string LogFileOf(string[] args)
        {
            for (int i = 0; i + 1 < args.Length; i++)
                if (args[i] == "--log") { try { return Path.GetFullPath(args[i + 1]); } catch (Exception) { return null; } }
            return null;
        }
    }

    sealed class Outcome
    {
        public bool Ok; public string Message; public string Detail; public string Target; public string Mode;
        // Vrai quand l'issue vient de `product_setup` (son message dit ce qui est vrai après coup : retour arrière fait
        // ou non) ; faux quand l'amorce a échoué elle-même.
        public bool FromSetup;
    }

    sealed class Installer
    {
        public const string Magic = "JVSETUP1";
        readonly Options options;
        public string Phase = "Préparation…";
        public Outcome Result;
        public Installer(Options options) { this.options = options; }

        void Log(string line)
        {
            if (options.LogFile == null) return;
            try { File.AppendAllText(options.LogFile, DateTime.UtcNow.ToString("o") + " " + line + Environment.NewLine, Encoding.UTF8); }
            catch (IOException) { }
        }

        static bool SafeEntry(string root, string name, out string full)
        {
            full = Path.GetFullPath(Path.Combine(root, name.Replace('/', Path.DirectorySeparatorChar)));
            string prefix = root.EndsWith(Path.DirectorySeparatorChar.ToString()) ? root : root + Path.DirectorySeparatorChar;
            return full.StartsWith(prefix, StringComparison.OrdinalIgnoreCase) && !Path.IsPathRooted(name) && name.IndexOf(':') < 0;
        }

        void Extract(string destination)
        {
            string self = Process.GetCurrentProcess().MainModule.FileName;
            using (var file = new FileStream(self, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                if (file.Length < 24) throw new InvalidDataException("installeur sans paquet");
                file.Seek(-24, SeekOrigin.End);
                var trailer = new byte[24];
                if (file.Read(trailer, 0, 24) != 24 || Encoding.ASCII.GetString(trailer, 0, 8) != Magic)
                    throw new InvalidDataException("installeur sans paquet (remorque absente)");
                long offset = BitConverter.ToInt64(trailer, 8), length = BitConverter.ToInt64(trailer, 16);
                if (offset < 0 || length <= 0 || offset + length > file.Length - 24) throw new InvalidDataException("remorque incohérente");
                using (var zip = new ZipArchive(new SubStream(file, offset, length), ZipArchiveMode.Read))
                {
                    int done = 0, total = zip.Entries.Count;
                    foreach (var entry in zip.Entries)
                    {
                        string full;
                        if (!SafeEntry(destination, entry.FullName, out full)) throw new InvalidDataException("nom refusé dans le paquet : " + entry.FullName);
                        if (entry.FullName.EndsWith("/")) { Directory.CreateDirectory(full); continue; }
                        Directory.CreateDirectory(Path.GetDirectoryName(full));
                        using (var input = entry.Open())
                        using (var output = new FileStream(full, FileMode.CreateNew, FileAccess.Write))
                            input.CopyTo(output);
                        done++;
                        if (done % 500 == 0) Phase = "Extraction des fichiers… " + (100 * done / Math.Max(1, total)) + " %";
                    }
                }
            }
        }

        // Un argument cité selon les règles de `CommandLineToArgvW` (celles du Python lancé) : les barres obliques inverses
        // qui précèdent un guillemet, ou la fin, sont doublées ; un guillemet intérieur (jamais dans un chemin Windows)
        // est retiré. Revue m2 : `"D:\Apps\Jarvis\"` avalait les arguments suivants.
        public static string Quote(string value)
        {
            string v = value.Replace("\"", "");
            var sb = new StringBuilder("\"");
            int slashes = 0;
            foreach (char c in v)
            {
                if (c == '\\') { slashes++; continue; }
                sb.Append('\\', slashes); slashes = 0; sb.Append(c);
            }
            sb.Append('\\', slashes * 2);
            return sb.Append('"').ToString();
        }

        string LastProgress(string path)
        {
            try
            {
                // Partage lecture/écriture : Python ajoute des lignes pendant cette lecture (File.ReadAllLines refusait
                // l'écriture concurrente et faisait tomber l'installation, essai réel de la Slice 07).
                var lines = new List<string>();
                using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                using (var reader = new StreamReader(stream, Encoding.UTF8))
                {
                    string line;
                    while ((line = reader.ReadLine()) != null) lines.Add(line);
                }
                for (int i = lines.Count - 1; i >= 0; i--)
                {
                    var row = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(lines[i]);
                    object message;
                    if (row != null && row.TryGetValue("message", out message) && message != null) return message.ToString();
                }
            }
            catch (Exception) { }
            return null;
        }

        public void Run()
        {
            string parent = Path.GetDirectoryName(options.Target.TrimEnd(Path.DirectorySeparatorChar));
            // `.jarvis-setup-<PID>-<hex>` : le PID de cette amorce dit à l'installation suivante (et à la désinstallation)
            // si le dossier a encore un propriétaire vivant ; sinon c'est un reste d'une amorce tuée (QA S10 R3).
            string work = Path.Combine(parent, ".jarvis-setup-" + Process.GetCurrentProcess().Id + "-"
                                               + Guid.NewGuid().ToString("N").Substring(0, 8));
            string package = Path.Combine(work, "package");
            string progress = Path.Combine(work, "progress.jsonl");
            string result = options.ResultFile ?? Path.Combine(work, "result.json");
            bool pythonStarted = false;
            try
            {
                Directory.CreateDirectory(package);
                Log("extraction vers " + package);
                Phase = "Extraction des fichiers…";
                Extract(package);
                string python = Path.Combine(package, "runtime", "python", "python.exe");
                var argv = new StringBuilder("-B -m jarvis.product_setup install --source " + Quote(package) + " --target " + Quote(options.Target)
                                             + " --progress " + Quote(progress) + " --result " + Quote(result));
                for (int i = 0; i < options.Passthrough.Count; i++) argv.Append(" ").Append(options.Passthrough[i].StartsWith("--") ? options.Passthrough[i] : Quote(options.Passthrough[i]));
                Log("python " + argv);
                // Une issue d'une installation précédente ne doit jamais passer pour celle-ci.
                if (File.Exists(result)) File.Delete(result);
                var start = new ProcessStartInfo(python, argv.ToString()) { UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = work,
                                                                            RedirectStandardOutput = true, RedirectStandardError = true,
                                                                            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8 };
                start.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
                var tail = new Queue<string>();
                DataReceivedEventHandler keep = (s, e) => { if (e.Data == null) return; lock (tail) { tail.Enqueue(e.Data); while (tail.Count > 40) tail.Dequeue(); } };
                using (var process = Process.Start(start))
                {
                    pythonStarted = true;
                    process.OutputDataReceived += keep; process.ErrorDataReceived += keep;
                    process.BeginOutputReadLine(); process.BeginErrorReadLine();
                    while (!process.WaitForExit(400))
                    {
                        string said = LastProgress(progress);
                        if (said != null) Phase = said;
                    }
                    process.WaitForExit();
                    Log("product_setup a rendu " + process.ExitCode);
                }
                string said_ = string.Join("\n", tail.ToArray());
                Result = ReadResult(result);
                if (!Result.Ok) Log("sortie de product_setup :\n" + said_);
                if (!Result.Ok && Result.Detail == null) Result.Detail = said_.Length > 600 ? said_.Substring(said_.Length - 600) : said_;
            }
            catch (Exception exc)
            {
                Log("ÉCHEC " + exc);
                // Avant Python, rien n'a touché au dossier de JARVIS (extraction à côté, dans un dossier de travail).
                Result = new Outcome { Ok = false, Detail = exc.GetType().Name + ": " + exc.Message,
                                       Message = pythonStarted ? "L'installation s'est interrompue. Relancez-la : elle reprend ou répare JARVIS si besoin."
                                                               : "L'installation a échoué avant de toucher au dossier de JARVIS : rien n'y a été modifié." };
            }
            finally
            {
                Phase = "Nettoyage…";
                try { if (Directory.Exists(work)) Directory.Delete(work, true); }
                catch (Exception exc) { Log("nettoyage incomplet de " + work + " : " + exc.Message); }
            }
        }

        static Outcome ReadResult(string path)
        {
            if (!File.Exists(path))
                return new Outcome { Ok = false, Message = "L'installation s'est arrêtée sans rendre son issue. Relancez-la : elle reprend ou répare JARVIS si besoin." };
            var row = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(path, Encoding.UTF8));
            Func<string, string> text = key => { object v; return row.TryGetValue(key, out v) && v != null ? v.ToString() : null; };
            object ok;
            return new Outcome { Ok = row.TryGetValue("ok", out ok) && ok is bool && (bool)ok, Message = text("message"),
                                 Detail = text("detail") ?? text("code"), Target = text("target"), Mode = text("mode"), FromSetup = true };
        }

        public static void LaunchJarvis(string target)
        {
            string pythonw = Path.Combine(target, "runtime", "python", "pythonw.exe");
            Process.Start(new ProcessStartInfo(pythonw, "-B -m jarvis launch") { UseShellExecute = false, WorkingDirectory = target });
        }
    }

    sealed class SetupForm : Form
    {
        readonly Options options; readonly Label title = new Label(), body = new Label(), status = new Label();
        readonly ProgressBar bar = new ProgressBar(); readonly Button primary = new Button(), secondary = new Button();
        readonly CheckBox openAfter = new CheckBox(); readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
        Installer installer; Thread worker; DateTime startedAt; bool finished;

        public SetupForm(Options options)
        {
            this.options = options;
            Text = "Installation de JARVIS";
            Font = new Font("Segoe UI", 10f);
            FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false; MinimizeBox = true;
            StartPosition = FormStartPosition.CenterScreen; ClientSize = new Size(560, 300); BackColor = Color.White;
            title.Text = "JARVIS — Presentation Edition"; title.Font = new Font("Segoe UI Semibold", 15f);
            title.SetBounds(28, 22, 500, 34);
            body.Text = "JARVIS s'installe pour vous seul, sans droits d'administrateur, dans :\n" + options.Target
                        + "\n\nVos présentations et vos réglages restent dans votre profil Windows : une mise à jour ou une réparation ne les touche pas.";
            body.SetBounds(28, 64, 504, 120);
            status.SetBounds(28, 190, 504, 24); status.ForeColor = Color.FromArgb(70, 70, 70);
            bar.SetBounds(28, 218, 504, 10); bar.Style = ProgressBarStyle.Marquee; bar.Visible = false;
            openAfter.Text = "Ouvrir JARVIS maintenant"; openAfter.Checked = true; openAfter.Visible = false; openAfter.SetBounds(28, 214, 300, 26);
            primary.Text = "Installer"; primary.SetBounds(412, 252, 120, 32);
            secondary.Text = "Annuler"; secondary.SetBounds(284, 252, 120, 32);
            primary.Click += delegate { if (finished) Finish(); else Begin(); };
            secondary.Click += delegate { Close(); };
            AcceptButton = primary; CancelButton = secondary;
            Controls.AddRange(new Control[] { title, body, status, bar, openAfter, primary, secondary });
            timer.Interval = 250; timer.Tick += delegate { Tick(); };
            FormClosing += (s, e) => { if (worker != null && worker.IsAlive) e.Cancel = true; };
        }

        void Begin()
        {
            primary.Enabled = false; secondary.Enabled = false; bar.Visible = true;
            installer = new Installer(options); startedAt = DateTime.Now;
            worker = new Thread(installer.Run) { IsBackground = true }; worker.Start(); timer.Start(); Tick();
        }

        void Tick()
        {
            int seconds = (int)(DateTime.Now - startedAt).TotalSeconds;
            status.Text = installer.Phase + "  ·  " + seconds + " s (l'installation prend en général trois à six minutes)";
            if (worker.IsAlive) return;
            timer.Stop(); bar.Visible = false; finished = true;
            var r = installer.Result;
            if (r != null && r.Ok)
            {
                title.Text = r.Mode == "update" ? "JARVIS est à jour" : r.Mode == "repair" ? "JARVIS est réparé" : "JARVIS est installé";
                body.Text = "Ouvrez JARVIS depuis le menu Démarrer ou le Bureau. Au premier lancement, JARVIS vous guide pour relier Claude et préparer le moteur de rendu des vidéos.";
                status.Text = "Terminé en " + seconds + " s."; openAfter.Visible = true; primary.Text = "Terminer";
                options.Target = r.Target ?? options.Target;
            }
            else
            {
                title.Text = "L'installation n'a pas abouti";
                // Le message de `product_setup` dit lui-même ce qui est vrai après coup (ancienne version remise en place,
                // rien d'installé, ou retour arrière impossible) : aucune phrase ajoutée ici (revue m9).
                body.Text = r != null && r.Message != null ? r.Message : "L'installation s'est arrêtée sans rendre son issue. Relancez-la : elle reprend ou répare JARVIS si besoin.";
                status.Text = r != null && r.Detail != null ? "Détail : " + (r.Detail.Length > 160 ? r.Detail.Substring(0, 160) + "…" : r.Detail) : "";
                primary.Text = "Fermer";
            }
            primary.Enabled = true;
        }

        void Finish()
        {
            if (openAfter.Visible && openAfter.Checked)
            {
                try { Installer.LaunchJarvis(options.Target); }
                catch (Exception exc) { MessageBox.Show(this, "JARVIS n'a pas pu être ouvert : " + exc.Message, "JARVIS", MessageBoxButtons.OK, MessageBoxIcon.Error); }
            }
            Close();
        }
    }

    static class Program
    {
        [DllImport("user32.dll")] static extern bool SetProcessDPIAware();

        [STAThread]
        static int Main(string[] args)
        {
            Options options;
            try { options = Options.Parse(args); }
            catch (ArgumentException exc)
            {
                if (!Options.WantsSilent(args)) { MessageBox.Show(exc.Message, "JARVIS", MessageBoxButtons.OK, MessageBoxIcon.Error); return 2; }
                // Silencieux (déploiement, CI) : jamais de boîte qui bloquerait sans personne pour la fermer (QA runtime m3).
                Refuse(Options.LogFileOf(args), "argument refusé : " + exc.Message);
                return 2;
            }
            if (options.Silent)
            {
                var installer = new Installer(options);
                installer.Run();
                bool ok = installer.Result != null && installer.Result.Ok;
                if (ok && options.Launch)
                {
                    // Installé, mais l'ouverture peut échouer : dit et journalisé, jamais un plantage muet (revue m8).
                    try { Installer.LaunchJarvis(installer.Result.Target ?? options.Target); }
                    catch (Exception exc) { Refuse(options.LogFile, "JARVIS est installé mais n'a pas pu être ouvert : " + exc.GetType().Name + ": " + exc.Message); return 3; }
                }
                return ok ? 0 : 1;
            }
            try { SetProcessDPIAware(); } catch (Exception) { }
            Application.EnableVisualStyles();
            Application.Run(new SetupForm(options));
            return 0;
        }

        // Refus en mode silencieux : `--log` s'il est donné, sinon `%TEMP%\jarvis-setup-error.log`, et la sortie d'erreur.
        static void Refuse(string logFile, string line)
        {
            string path = logFile ?? Path.Combine(Path.GetTempPath(), "jarvis-setup-error.log");
            try { File.AppendAllText(path, DateTime.UtcNow.ToString("o") + " " + line + Environment.NewLine, Encoding.UTF8); }
            catch (Exception) { }
            try { Console.Error.WriteLine(line); } catch (Exception) { }
        }
    }
}
