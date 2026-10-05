// Lançador com ícone: só chama o .bat que está na mesma pasta que ele.
// Existe para o instalador e o portal terem ícone já no pacote enviado
// (um atalho .lnk guarda caminho completo e não sobrevive à cópia).
// Compilado pelo ferramentas\gerar_lancadores.py.

using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;

static class Lancador
{
#if INSTALAR
    const string BAT = "Instalar.bat";
#else
    const string BAT = "Portal.bat";
#endif

    static int Main()
    {
        string pasta = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        string bat = Path.Combine(pasta, BAT);

        if (!File.Exists(bat))
        {
            Console.WriteLine(BAT + " nao encontrado em " + pasta);
            Console.WriteLine("Este arquivo precisa ficar na pasta do Transcritor.");
            if (!Console.IsInputRedirected) Console.ReadKey(true);
            return 1;
        }

        // Ctrl+C fica com o .bat (mesma janela); o lançador só espera.
        Console.CancelKeyPress += (s, e) => e.Cancel = true;

        string cmd = Environment.GetEnvironmentVariable("ComSpec") ?? "cmd.exe";
        var inicio = new ProcessStartInfo(cmd, "/c \"\"" + bat + "\"\"")
        {
            UseShellExecute = false,
            WorkingDirectory = pasta,
        };

        using (var processo = Process.Start(inicio))
        {
            processo.WaitForExit();
            return processo.ExitCode;
        }
    }
}
