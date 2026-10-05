// Lançadores com ícone da raiz do projeto. Existem para o instalador e o
// portal terem ícone já no pacote enviado (um atalho .lnk guarda caminho
// completo e não sobrevive à cópia).
//   INSTALAR: chama o Instalar.bat ao lado, na mesma janela.
//   PORTAL:   sobe o portal sem janela (equivale ao Portal.bat); ele é
//             desligado pelo botão "Encerrar portal" da própria página.
// Compilado pelo ferramentas\gerar_lancadores.py.

using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;

static class Lancador
{
    static readonly string PASTA =
        Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);

#if INSTALAR

    static int Main()
    {
        string bat = Path.Combine(PASTA, "Instalar.bat");

        if (!File.Exists(bat))
        {
            Console.WriteLine("Instalar.bat nao encontrado em " + PASTA);
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
            WorkingDirectory = PASTA,
        };

        using (var processo = Process.Start(inicio))
        {
            processo.WaitForExit();
            return processo.ExitCode;
        }
    }

#else

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern int MessageBoxW(IntPtr janela, string texto, string titulo, uint tipo);

    static int Avisar(string texto)
    {
        MessageBoxW(IntPtr.Zero, texto, "Transcritor", 0x30);  // ícone de aviso
        return 1;
    }

    static int Main()
    {
        string servidor = Path.Combine(PASTA, "src", "portal", "servidor.py");

        if (!File.Exists(servidor))
            return Avisar("Este arquivo precisa ficar na pasta do Transcritor.\n\n" +
                          "Não encontrei: " + servidor);

        // Usa o ambiente virtual criado pelo instalador, se existir.
        string python = Path.Combine(PASTA, ".venv", "Scripts", "python.exe");
        if (!File.Exists(python)) python = "python";

        var inicio = new ProcessStartInfo(python, "\"" + servidor + "\" --segundo-plano")
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            WorkingDirectory = PASTA,
        };

        // Não deixa __pycache__ espalhado pela árvore do projeto.
        inicio.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";

        const string DICA =
            "Se ainda não instalou, execute o \"Instalar Transcritor\".\n" +
            "Para ver o erro, abra o Portal.bat desta pasta.";

        Process processo;

        try
        {
            processo = Process.Start(inicio);
        }
        catch (Exception)
        {
            return Avisar("Não foi possível iniciar o portal (Python não encontrado).\n\n" + DICA);
        }

        // Sem janela ninguém veria o erro: se cair logo de cara, avisa.
        // (Sair com 0 é o caso "já estava aberto": só abriu o navegador.)
        if (processo.WaitForExit(6000) && processo.ExitCode != 0)
            return Avisar("O portal não conseguiu iniciar.\n\n" + DICA);

        return 0;
    }

#endif
}
