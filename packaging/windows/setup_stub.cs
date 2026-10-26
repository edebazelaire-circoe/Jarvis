// Amorce de l'installeur Windows de JARVIS Presentation Edition (Slice 07, docs/product-install.md > Installer).
//
// Compilée par `build_package.py installer` avec le compilateur C# du .NET Framework 4.x livré avec Windows
// (aucun outil à installer : recommandation sous HV-PACKAGE-10). Le paquet (dossier de la Slice 06) est zippé et
// ACCOLÉ à la fin de cet exécutable, suivi d'une remorque de 24 octets : "JVSETUP1" + position (int64) + longueur
// (int64) du zip. L'amorce ne décide rien : elle extrait le paquet à côté de la cible, puis laisse le Python DU
// PAQUET faire l'installation (`python -B -m jarvis.product_setup install`), dont elle lit la progression et l'issue.
//
// Ligne de commande (déploiement silencieux, CI, essais en dossiers simulés) :
//   /S | --silent        aucune fenêtre ; code de sortie 0 = installé
//   --target DIR         dossier d'installation (défaut %LOCALAPPDATA%\Programs\CIRCOE\Jarvis)
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
                    string v = args[++i];
                    if (a == "--target") o.Target = Path.GetFullPath(v);
                    else if (a == "--log") o.LogFile = Path.GetFullPath(v);
                    else if (a == "--result") o.ResultFile = Path.GetFullPath(v);
                    else { o.Passthrough.Add(a); o.Passthrough.Add(Path.GetFullPath(v)); }
                }
                else throw new ArgumentException("argument inconnu : " + a);
            }
            if (o.Target == null)
            {
                string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                o.Target = Path.Combine(local, "Programs", "CIRCOE", "Jarvis");
            }
            return o;
        }
    }

    sealed class Outcome
    {
        public bool Ok; public string Message; public string Detail; public string Target; public string Mode;
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

        static string Quote(string value) { return "\"" + value.Replace("\"", "") + "\""; }

        string LastProgress(string path)
        {
            try
            {
                string[] lines = File.ReadAllLines(path, Encoding.UTF8);
                for (int i = lines.Length - 1; i >= 0; i--)
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
            string work = Path.Combine(parent, ".jarvis-setup-" + Guid.NewGuid().ToString("N").Substring(0, 12));
            string package = Path.Combine(work, "package");
            string progress = Path.Combine(work, "progress.jsonl");
            string result = options.ResultFile ?? Path.Combine(work, "result.json");
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
                var start = new ProcessStartInfo(python, argv.ToString()) { UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = work };
                start.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
                using (var process = Process.Start(start))
                {
                    while (!process.WaitForExit(400))
                    {
                        string said = LastProgress(progress);
                        if (said != null) Phase = said;
                    }
                    Log("product_setup a rendu " + process.ExitCode);
                }
                Result = ReadResult(result);
            }
            catch (Exception exc)
            {
                Log("ÉCHEC " + exc);
                Result = new Outcome { Ok = false, Message = "L'installation a échoué.", Detail = exc.GetType().Name + ": " + exc.Message };
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
            if (!File.Exists(path)) return new Outcome { Ok = false, Message = "L'installation s'est arrêtée sans rendre son issue." };
            var row = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(path, Encoding.UTF8));
            Func<string, string> text = key => { object v; return row.TryGetValue(key, out v) && v != null ? v.ToString() : null; };
            object ok;
            return new Outcome { Ok = row.TryGetValue("ok", out ok) && ok is bool && (bool)ok, Message = text("message"),
                                 Detail = text("detail") ?? text("code"), Target = text("target"), Mode = text("mode") };
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
            status.Text = installer.Phase + "  ·  " + seconds + " s (l'installation prend en général une à trois minutes)";
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
                body.Text = (r != null && r.Message != null ? r.Message : "Erreur inconnue.") + "\n\nRien n'a été effacé : une installation précédente reste en place.";
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
            catch (ArgumentException exc) { MessageBox.Show(exc.Message, "JARVIS", MessageBoxButtons.OK, MessageBoxIcon.Error); return 2; }
            if (options.Silent)
            {
                var installer = new Installer(options);
                installer.Run();
                if (installer.Result != null && installer.Result.Ok && options.Launch) Installer.LaunchJarvis(installer.Result.Target ?? options.Target);
                return installer.Result != null && installer.Result.Ok ? 0 : 1;
            }
            try { SetProcessDPIAware(); } catch (Exception) { }
            Application.EnableVisualStyles();
            Application.Run(new SetupForm(options));
            return 0;
        }
    }
}
