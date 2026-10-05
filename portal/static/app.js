/* Portal do Transcritor — interface (JS puro, sem dependências).
 * Todo texto vindo de arquivos/servidor entra no DOM só via textContent. */
(() => {
  "use strict";

  const TOKEN = document.querySelector('meta[name="portal-token"]').content;
  const app = document.getElementById("app");
  const modalFundo = document.getElementById("modal-fundo");

  let rotaId = 0;            // muda a cada navegação: encerra pollers antigos
  let timers = [];
  let config = null;

  // ---------------------------------------------------------------- utilidades

  function h(tag, attrs, ...filhos) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "texto") el.textContent = v;
      else if (v === true) el.setAttribute(k, "");
      else el.setAttribute(k, v);
    }
    for (const f of filhos.flat()) {
      if (f === null || f === undefined || f === false) continue;
      el.append(f.nodeType ? f : document.createTextNode(String(f)));
    }
    return el;
  }

  function trocar(el, ...filhos) {
    el.replaceChildren(...filhos.flat().filter((f) => f !== null && f !== undefined && f !== false));
  }

  async function api(caminho, opcoes) {
    const o = opcoes || {};
    const init = { method: o.method || "GET", headers: {} };
    if (init.method !== "GET") {
      init.headers["Content-Type"] = "application/json";
      init.headers["X-Token"] = TOKEN;
      init.body = JSON.stringify(o.corpo || {});
    }
    const resp = await fetch(caminho, init);
    let dados = null;
    try { dados = await resp.json(); } catch (_) { /* sem corpo */ }
    if (!resp.ok) {
      const e = new Error((dados && dados.erro) || `erro ${resp.status}`);
      e.status = resp.status;
      throw e;
    }
    return dados;
  }

  function fmtTam(b) {
    if (b === null || b === undefined) return "";
    const u = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
    return `${b >= 100 || i === 0 ? Math.round(b) : b.toFixed(1)} ${u[i]}`;
  }

  function fmtDur(s) {
    if (s === null || s === undefined) return "";
    s = Math.round(s);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}min ${s % 60}s`;
    return `${Math.floor(m / 60)}h ${m % 60}min`;
  }

  function fmtData(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return isNaN(d) ? iso : d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  }

  function limparTimers() {
    timers.forEach(clearTimeout);
    timers = [];
  }

  function rotulo(etapa) {
    const e = (config.etapas || []).find((x) => x.chave === etapa);
    return e ? e.rotulo : etapa;
  }

  function pilula(texto, tipo) {
    return h("span", { class: `pilula ${tipo || ""}` }, texto);
  }

  const ROTULO_RUN = {
    preparando: ["Preparando (copiando arquivos)", "rodando"],
    rodando: ["Em andamento", "rodando"],
    parando: ["Parando após o arquivo atual", "aviso"],
    concluida: ["Concluída", "ok"],
    concluida_com_falhas: ["Concluída com falhas", "aviso"],
    cancelada: ["Cancelada", "aviso"],
    interrompida: ["Interrompida", "erro"],
    erro: ["Erro", "erro"],
  };

  const EM_ANDAMENTO = ["preparando", "rodando", "parando"];

  // ---------------------------------------------------------------- modal de pastas

  function abrirModalPastas(inicial, aoEscolher) {
    let atual = inicial || "";

    const fechar = () => { modalFundo.hidden = true; modalFundo.replaceChildren(); };

    async function carregar(caminho) {
      let dados;
      try {
        dados = await api(`/api/pastas?caminho=${encodeURIComponent(caminho)}`);
      } catch (e) {
        alert(e.message);
        return;
      }
      atual = dados.caminho;

      const lista = h("ul", {});
      if (dados.caminho && dados.pai !== null) {
        lista.append(h("li", {}, h("button", {
          onclick: () => carregar(dados.pai), texto: "⬑ Subir um nível",
        })));
      }
      for (const p of dados.pastas) {
        lista.append(h("li", {}, h("button", {
          onclick: () => carregar(p.caminho), texto: `📁 ${p.nome}`,
        })));
      }
      if (!dados.pastas.length) lista.append(h("li", { class: "vazio" }, "Nenhuma subpasta."));

      const usar = h("button", {
        class: "primario", disabled: !dados.caminho,
        onclick: () => { fechar(); aoEscolher(atual); },
      }, "Usar esta pasta");

      modalFundo.replaceChildren(h("div", { class: "modal", role: "dialog", "aria-label": "Escolher pasta" },
        h("header", {},
          h("h2", {}, "Escolher pasta"),
          h("div", { class: "caminho" }, dados.caminho || "Unidades do computador"),
        ),
        lista,
        h("footer", {},
          h("span", { class: "sutil espaco" },
            dados.caminho ? `${dados.midias} arquivo(s) de áudio/vídeo nesta pasta` : ""),
          h("button", { onclick: fechar }, "Cancelar"),
          usar,
        ),
      ));
    }

    modalFundo.hidden = false;
    carregar(atual);
  }

  modalFundo.addEventListener("click", (e) => {
    if (e.target === modalFundo) { modalFundo.hidden = true; modalFundo.replaceChildren(); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modalFundo.hidden) { modalFundo.hidden = true; modalFundo.replaceChildren(); }
  });

  // ---------------------------------------------------------------- Nova execução

  const PRESETS = {
    tudo: ["mp3", "transcricao", "resumo", "consolidar"],
    audio: ["mp3"],
    transcricao: ["transcricao"],
    resumo: ["resumo"],
  };
  const PRESET_ROTULOS = [
    ["tudo", "Tudo"], ["audio", "Só áudio"], ["transcricao", "Só transcrição"],
    ["resumo", "Só resumo"], ["personalizado", "Personalizado"],
  ];

  function viewNova() {
    const minhaRota = rotaId;
    const est = {
      origem: localStorage.getItem("ultima_origem") || "",
      recursivo: false,
      preset: "tudo",
      etapas: new Set(PRESETS.tudo),
      plano: null,
      sel: new Set(),
      analisando: false,
    };

    const campoPasta = h("input", {
      type: "text", class: "campo-pasta", value: est.origem,
      placeholder: "Caminho da pasta com os vídeos/áudios (ex.: D:\\Reunioes)",
      "aria-label": "Pasta de origem",
    });
    const areaPlano = h("div", {});
    const areaPresets = h("div", { class: "presets" });
    const areaEtapas = h("div", { class: "etapas" });
    const chkSub = h("input", { type: "checkbox" });

    campoPasta.addEventListener("input", () => { est.origem = campoPasta.value.trim(); });
    chkSub.addEventListener("change", () => { est.recursivo = chkSub.checked; if (est.plano) analisar(); });

    function presetAtual() {
      for (const [k, v] of Object.entries(PRESETS)) {
        if (v.length === est.etapas.size && v.every((e) => est.etapas.has(e))) return k;
      }
      return "personalizado";
    }

    function desenharControles() {
      est.preset = presetAtual();
      areaPresets.replaceChildren(...PRESET_ROTULOS.map(([k, r]) => h("button", {
        "aria-pressed": String(est.preset === k),
        onclick: () => {
          if (k === "personalizado") return;
          est.etapas = new Set(PRESETS[k]);
          desenharControles();
          if (est.plano) analisar();
        },
      }, r)));

      areaEtapas.replaceChildren(...config.etapas.map((e) => {
        const semToken = e.chave === "diarizacao" && !config.tem_token_hf;
        const chk = h("input", { type: "checkbox", disabled: semToken });
        chk.checked = est.etapas.has(e.chave) && !semToken;
        chk.addEventListener("change", () => {
          if (chk.checked) est.etapas.add(e.chave); else est.etapas.delete(e.chave);
          desenharControles();
          if (est.plano) analisar();
        });
        return h("label", { class: "opcao" }, chk, e.rotulo,
          semToken ? h("span", { class: "dica" }, "(precisa do token da Hugging Face no config.json)") : null);
      }));
    }

    async function analisar() {
      est.origem = campoPasta.value.trim();
      if (!est.origem) { areaPlano.replaceChildren(h("div", { class: "aviso-faixa erro" }, "Informe a pasta de origem.")); return; }
      if (!est.etapas.size) { areaPlano.replaceChildren(h("div", { class: "aviso-faixa erro" }, "Selecione ao menos uma etapa.")); return; }
      est.analisando = true;
      areaPlano.replaceChildren(h("div", { class: "vazio" }, "Analisando a pasta…"));
      try {
        const plano = await api("/api/plano", { method: "POST", corpo: {
          origem: est.origem, etapas: [...est.etapas], recursivo: est.recursivo } });
        if (minhaRota !== rotaId) return;
        localStorage.setItem("ultima_origem", est.origem);
        const anterior = est.plano ? est.sel : null;
        est.plano = plano;
        est.sel = new Set(plano.itens.filter((i) => !i.excluido
          && (!anterior || anterior.has(i.nome))).map((i) => i.nome));
        desenharPlano();
      } catch (e) {
        est.plano = null;
        areaPlano.replaceChildren(h("div", { class: "aviso-faixa erro" }, e.message));
      }
      est.analisando = false;
    }

    function textoAcao(s) {
      if (s.acao === "executar") return pilula("Executar", "info");
      if (s.acao === "pular") return pilula("Já existe", "");
      return pilula("Bloqueado", "erro");
    }

    function desenharPlano() {
      const p = est.plano;
      if (!p.itens.length) {
        areaPlano.replaceChildren(h("div", { class: "cartao vazio" },
          "Nenhum arquivo de áudio ou vídeo encontrado nesta pasta."));
        return;
      }

      const escolhidos = p.itens.filter((i) => est.sel.has(i.nome));
      const bloqueados = escolhidos.flatMap((i) => Object.entries(i.estagios)
        .filter(([, s]) => s.acao === "bloqueado").map(([e, s]) => ({ item: i.nome, etapa: e, ...s })));
      const copiar = escolhidos.filter((i) => i.copiar).reduce((a, i) => a + i.tamanho, 0);
      const algoParaFazer = escolhidos.some((i) => Object.values(i.estagios).some((s) => s.acao === "executar"));

      const todos = h("input", { type: "checkbox", "aria-label": "Selecionar todos" });
      const validos = p.itens.filter((i) => !i.excluido);
      todos.checked = validos.length > 0 && validos.every((i) => est.sel.has(i.nome));
      todos.addEventListener("change", () => {
        est.sel = new Set(todos.checked ? validos.map((i) => i.nome) : []);
        desenharPlano();
      });

      const cab = h("tr", {}, h("th", {}, todos), h("th", {}, "Arquivo"), h("th", {}, "Tamanho"),
        ...p.etapas.map((e) => h("th", {}, rotulo(e))), h("th", {}, "Cópia"));

      const linhas = p.itens.map((i) => {
        if (i.excluido) {
          return h("tr", { class: "excluido" }, h("td", {}), h("td", { class: "nome" }, i.nome),
            h("td", { class: "tam" }, fmtTam(i.tamanho)),
            h("td", { colspan: String(p.etapas.length + 1) }, pilula("Fora desta execução", ""), " ", i.excluido));
        }
        const chk = h("input", { type: "checkbox", "aria-label": `Selecionar ${i.nome}` });
        chk.checked = est.sel.has(i.nome);
        chk.addEventListener("change", () => {
          if (chk.checked) est.sel.add(i.nome); else est.sel.delete(i.nome);
          desenharPlano();
        });
        return h("tr", {}, h("td", {}, chk), h("td", { class: "nome" }, i.nome),
          h("td", { class: "tam" }, fmtTam(i.tamanho)),
          ...p.etapas.map((e) => {
            const s = i.estagios[e];
            return h("td", { class: "celula" }, textoAcao(s),
              s.motivo ? h("span", { class: "sutil detalhe" }, s.motivo) : null);
          }),
          h("td", { class: "sutil" }, i.copiar ? `Copiar para ${i.copiar.area}` : "—"));
      });

      const sugeridas = [...new Set(bloqueados.map((b) => b.sugerir).filter(Boolean))];

      const iniciar = h("button", { class: "primario", disabled: !escolhidos.length || bloqueados.length > 0 || !algoParaFazer,
        onclick: async () => {
          iniciar.disabled = true;
          try {
            const r = await api("/api/execucoes", { method: "POST", corpo: {
              origem: p.origem, etapas: p.etapas, itens: [...est.sel], recursivo: est.recursivo } });
            location.hash = `#/execucao/${r.id}`;
          } catch (e) {
            alert(e.message);
            iniciar.disabled = false;
          }
        } }, "Iniciar execução");

      trocar(areaPlano,
        bloqueados.length ? h("div", { class: "aviso-faixa erro" },
          `${bloqueados.length} etapa(s) bloqueada(s) nos arquivos selecionados (falta algo de uma etapa anterior). `,
          sugeridas.length ? h("button", { onclick: () => {
            sugeridas.forEach((e) => est.etapas.add(e));
            desenharControles();
            analisar();
          } }, `Marcar: ${sugeridas.map(rotulo).join(", ")}`) : null) : null,
        escolhidos.length && !algoParaFazer && !bloqueados.length
          ? h("div", { class: "aviso-faixa info" }, "Tudo isto já existe na área de trabalho — não há nada a fazer.") : null,
        h("div", { class: "cartao" },
          h("div", { class: "linha" },
            h("h2", {}, `${p.itens.length} arquivo(s) na pasta`),
            h("span", { class: "sutil" }, `${escolhidos.length} selecionado(s)` +
              (copiar ? ` · copiar ${fmtTam(copiar)} para a área de trabalho` : "")),
            h("span", { class: "espaco" }), iniciar),
          h("div", { class: "tabela-rolagem" }, h("table", {}, h("thead", {}, cab), h("tbody", {}, linhas))),
        ),
      );
    }

    desenharControles();

    app.replaceChildren(
      h("h1", {}, "Nova execução"),
      h("p", { class: "sub" }, "Aponte uma pasta, escolha as etapas e acompanhe cada arquivo. A pasta de origem nunca é alterada: os arquivos são copiados para a área de trabalho."),
      h("div", { class: "cartao" },
        h("h2", {}, "1. Pasta de origem"),
        h("div", { class: "linha" }, campoPasta,
          h("button", { onclick: () => abrirModalPastas(campoPasta.value.trim(), (c) => { campoPasta.value = c; est.origem = c; analisar(); }) }, "Procurar…"),
          h("label", { class: "opcao" }, chkSub, "Incluir subpastas"),
          h("button", { class: "primario", onclick: analisar }, "Analisar"))),
      h("div", { class: "cartao" },
        h("h2", {}, "2. O que executar"), areaPresets, areaEtapas),
      areaPlano,
    );

    if (est.origem) analisar();
  }

  // ---------------------------------------------------------------- Execução (acompanhamento)

  const MOTIVOS = {
    ja_existe: "Já existia",
    sem_transcricao_ou_resumo: "Sem transcrição/resumo",
  };

  function celulaEtapa(e) {
    if (!e) return h("td", {}, "—");
    const conteudo = [];
    switch (e.estado) {
      case "pendente": conteudo.push(pilula("Aguardando", "")); break;
      case "rodando":
        conteudo.push(pilula(e.dispositivo === "cpu" ? "Rodando (CPU)" : "Rodando", "rodando"));
        conteudo.push(h("div", { class: e.pct === undefined || e.pct === null ? "barra indeterminada" : "barra" },
          h("span", { style: e.pct !== undefined && e.pct !== null ? `width:${e.pct}%` : null })));
        if (e.pct !== undefined && e.pct !== null) conteudo.push(h("span", { class: "sutil detalhe" }, `${e.pct}%`));
        break;
      case "ok":
        conteudo.push(pilula("Pronto", "ok"));
        if (e.dur !== undefined) conteudo.push(h("span", { class: "sutil detalhe" }, fmtDur(e.dur)));
        if (e.nota === "recuperado_cpu") conteudo.push(h("span", { class: "sutil detalhe" }, "recuperado na CPU"));
        break;
      case "pulado":
        conteudo.push(pilula(MOTIVOS[e.motivo] || "Pulado", "info")); break;
      case "falhou":
        conteudo.push(pilula("Falhou", "erro"));
        if (e.motivo) conteudo.push(h("span", { class: "sutil detalhe" }, e.motivo));
        break;
      case "aguardando_cpu":
        conteudo.push(pilula("Retentando na CPU", "aviso"));
        if (e.motivo) conteudo.push(h("span", { class: "sutil detalhe" }, `GPU: ${e.motivo}`));
        break;
      case "sem_entrada": conteudo.push(pilula("Sem entrada", "")); break;
      case "nao_executado": conteudo.push(pilula("Não executado", "")); break;
      case "cancelado": conteudo.push(pilula("Interrompido", "aviso")); break;
      default: conteudo.push(pilula(e.estado, ""));
    }
    return h("td", { class: "celula" }, conteudo);
  }

  function celulaCopia(c) {
    if (!c) return h("td", { class: "sutil" }, "—");
    if (c.estado === "rodando") {
      return h("td", { class: "celula" }, pilula("Copiando", "rodando"),
        h("div", { class: "barra" }, h("span", { style: `width:${c.pct || 0}%` })));
    }
    if (c.estado === "ok") {
      const t = { reaproveitado: "Já estava lá", hardlink: "Atalho", copiado: "Copiado" }[c.nota] || "Copiado";
      return h("td", {}, pilula(t, "ok"));
    }
    return h("td", { class: "celula" }, pilula("Falhou", "erro"), h("span", { class: "sutil detalhe" }, c.motivo || ""));
  }

  function viewExecucao(id) {
    const minhaRota = rotaId;
    const cab = h("div", {});
    const faixas = h("div", {});
    const tabela = h("div", { class: "cartao" });
    const falhas = h("div", {});
    const preLog = h("pre", { class: "log", tabindex: "0", "aria-label": "Log da execução" });
    let ultimoEstado = null;

    app.replaceChildren(cab, faixas, tabela, falhas,
      h("div", { class: "cartao" }, h("h2", {}, "Log ao vivo"), preLog));

    async function acao(caminho, confirmar) {
      if (confirmar && !confirm(confirmar)) return;
      try {
        const r = await api(caminho, { method: "POST" });
        if (r && r.id) location.hash = `#/execucao/${r.id}`;
        else atualizar();
      } catch (e) { alert(e.message); }
    }

    function desenhar(s) {
      const [txt, tipo] = ROTULO_RUN[s.estado_run] || [s.estado_run, ""];
      const ativo = EM_ANDAMENTO.includes(s.estado_run);

      const botoes = [];
      if (ativo) {
        botoes.push(h("button", { disabled: s.estado_run === "parando" || s.flag_parar,
          onclick: () => acao(`/api/execucoes/${id}/parar`) }, "Parar após o arquivo atual"));
        botoes.push(h("button", { class: "perigo",
          onclick: () => acao(`/api/execucoes/${id}/cancelar`,
            "Cancelar agora? O arquivo em andamento será interrompido e precisará ser refeito.") }, "Cancelar agora"));
      } else if (["interrompida", "cancelada", "erro", "concluida_com_falhas"].includes(s.estado_run)) {
        botoes.push(h("button", { class: "primario",
          onclick: () => acao(`/api/execucoes/${id}/retomar`) }, "Retomar (nova execução, pula o que já existe)"));
      }

      cab.replaceChildren(h("div", { class: "cartao" },
        h("div", { class: "linha" },
          h("div", {}, h("h1", {}, `Execução ${fmtData(s.criado)}`),
            h("p", { class: "sub" }, s.origem, " · ", s.etapas.map(rotulo).join(" → "),
              s.dispositivo ? ` · ${s.dispositivo.toUpperCase()}` : "",
              s.fase_atual ? ` · fase atual: ${rotulo(s.fase_atual)}` : "")),
          h("span", { class: "espaco" }), pilula(txt, tipo), ...botoes)));

      const f = [];
      if (s.pausa_termica) {
        f.push(h("div", { class: "aviso-faixa" },
          `GPU quente (${s.pausa_termica.temp} °C) — pausado até esfriar abaixo de ${s.pausa_termica.retomar_abaixo} °C. ` +
          "Isso protege a placa e evita lentidão."));
      }
      if (s.ollama === "iniciado_por_nos" && ativo) {
        f.push(h("div", { class: "aviso-faixa info" }, "Ollama iniciado por esta execução (será encerrado ao final)."));
      }
      if (s.ollama === "indisponivel") {
        f.push(h("div", { class: "aviso-faixa erro" }, "Ollama não está disponível — os resumos vão falhar."));
      }
      if (s.estado_run === "interrompida") {
        f.push(h("div", { class: "aviso-faixa erro" }, "O processo parou sem terminar (fechado por fora ou travado). Use Retomar: o que já foi feito é reaproveitado."));
      }
      if (s.erro) f.push(h("div", { class: "aviso-faixa erro" }, `Erro: ${s.erro}`));
      faixas.replaceChildren(...f);

      const itens = Object.values(s.itens);
      const cont = { ok: 0, rodando: 0, pulado: 0, falhou: 0, pendente: 0 };
      itens.forEach((i) => Object.values(i.etapas).forEach((e) => {
        if (e.estado === "ok") cont.ok++;
        else if (e.estado === "rodando" || e.estado === "aguardando_cpu") cont.rodando++;
        else if (e.estado === "pulado") cont.pulado++;
        else if (e.estado === "falhou" || e.estado === "cancelado") cont.falhou++;
        else if (e.estado === "pendente") cont.pendente++;
      }));

      const temCopia = itens.some((i) => i.copia);

      tabela.replaceChildren(
        h("div", { class: "resumo-contagem", style: "margin-bottom:14px" },
          ...[["Prontas", cont.ok], ["Em andamento", cont.rodando], ["Já existiam", cont.pulado],
            ["Falhas", cont.falhou], ["Aguardando", cont.pendente]].map(([r, n]) =>
            h("div", {}, h("strong", {}, String(n)), h("span", {}, r)))),
        h("div", { class: "tabela-rolagem" }, h("table", {},
          h("thead", {}, h("tr", {}, h("th", {}, "Arquivo"), temCopia ? h("th", {}, "Cópia") : null,
            ...s.etapas.map((e) => h("th", {}, rotulo(e))))),
          h("tbody", {}, itens.map((i) => h("tr", {},
            h("td", { class: "nome" }, i.nome, h("div", { class: "sutil" }, fmtTam(i.tamanho))),
            temCopia ? celulaCopia(i.copia) : null,
            ...s.etapas.map((e) => celulaEtapa(i.etapas[e]))))))));

      const lf = (s.falhas || []);
      trocar(falhas, lf.length ? h("div", { class: "cartao" },
        h("h2", {}, "Falhas e retentativas"),
        h("ul", {}, lf.map((x) => h("li", {}, `[${String(x.etapa).toUpperCase()}] ${x.arquivo} — ${x.resultado}`)))) : null);
    }

    async function atualizarLog() {
      try {
        const r = await api(`/api/execucoes/${id}/log?linhas=300`);
        const noFim = preLog.scrollTop + preLog.clientHeight >= preLog.scrollHeight - 30;
        preLog.textContent = r.linhas.join("\n");
        if (noFim) preLog.scrollTop = preLog.scrollHeight;
      } catch (_) { /* ignora */ }
    }

    async function atualizar() {
      if (minhaRota !== rotaId) return;
      try {
        const s = await api(`/api/execucoes/${id}`);
        if (minhaRota !== rotaId) return;
        ultimoEstado = s;
        desenhar(s);
        await atualizarLog();
        if (EM_ANDAMENTO.includes(s.estado_run)) timers.push(setTimeout(atualizar, 1000));
      } catch (e) {
        if (e.status === 404) { app.replaceChildren(h("div", { class: "cartao vazio" }, "Execução não encontrada.")); return; }
        timers.push(setTimeout(atualizar, 3000));  // servidor pode ter reiniciado
      }
    }

    atualizar();
  }

  // ---------------------------------------------------------------- Lista de execuções

  async function viewExecucoes() {
    const minhaRota = rotaId;
    app.replaceChildren(h("h1", {}, "Execuções"), h("div", { class: "vazio" }, "Carregando…"));
    try {
      const r = await api("/api/execucoes");
      if (minhaRota !== rotaId) return;
      const linhas = r.execucoes.map((x) => {
        const [t, tipo] = ROTULO_RUN[x.estado_run] || [x.estado_run, ""];
        const c = x.contagem || {};
        return h("tr", {},
          h("td", {}, h("a", { href: `#/execucao/${x.id}` }, fmtData(x.criado))),
          h("td", { class: "nome" }, x.origem),
          h("td", {}, x.etapas.map(rotulo).join(" → ")),
          h("td", { class: "num" }, String(x.arquivos)),
          h("td", {}, pilula(t, tipo)),
          h("td", { class: "sutil" }, `${c.ok || 0} prontas · ${c.falhou || 0} falhas · ${c.pulado || 0} já existiam`));
      });
      app.replaceChildren(h("h1", {}, "Execuções"),
        h("p", { class: "sub" }, "Histórico das execuções feitas pelo portal."),
        r.execucoes.length ? h("div", { class: "cartao tabela-rolagem" }, h("table", {},
          h("thead", {}, h("tr", {}, ["Início", "Pasta de origem", "Etapas", "Arquivos", "Estado", "Resultado"].map((t) => h("th", {}, t)))),
          h("tbody", {}, linhas))) : h("div", { class: "cartao vazio" }, "Nenhuma execução ainda."));
    } catch (e) {
      app.replaceChildren(h("div", { class: "aviso-faixa erro" }, e.message));
    }
  }

  // ---------------------------------------------------------------- Resultados

  function viewResultados() {
    const minhaRota = rotaId;
    let aba = "concluidos";
    let busca = "";
    const lista = h("div", { class: "lista-resultados" });
    const leitor = h("div", {});
    const abas = h("div", { class: "abas", role: "tablist" });
    const campo = h("input", { type: "search", placeholder: "Buscar pelo nome…", "aria-label": "Buscar" });
    let debounce = null;
    campo.addEventListener("input", () => {
      clearTimeout(debounce);
      debounce = setTimeout(() => { busca = campo.value.trim(); carregar(); }, 250);
    });

    function desenharAbas() {
      abas.replaceChildren(...[["concluidos", "Concluídos"], ["parciais", "Parciais (área de trabalho)"]].map(([k, r]) =>
        h("button", { role: "tab", "aria-selected": String(aba === k),
          onclick: () => { aba = k; leitor.replaceChildren(); desenharAbas(); carregar(); } }, r)));
    }

    async function carregar() {
      lista.replaceChildren(h("div", { class: "vazio" }, "Carregando…"));
      try {
        const r = await api(`/api/resultados?aba=${aba}&busca=${encodeURIComponent(busca)}`);
        if (minhaRota !== rotaId) return;
        if (!r.itens.length) {
          lista.replaceChildren(h("div", { class: "cartao vazio" },
            aba === "concluidos" ? "Nenhuma reunião concluída ainda." : "Nada pendente na área de trabalho."));
          return;
        }
        lista.replaceChildren(...r.itens.map((i) => h("button", { class: "item-resultado", onclick: () => abrir(i) },
          h("span", { class: "nome" }, i.nome),
          i.resumo ? pilula("Resumo", "ok") : null,
          i.transcricao ? pilula("Transcrição", "info") : null,
          i.diarizado ? pilula("Diarização", "info") : null,
          i.audio && aba === "parciais" ? pilula("Áudio", "") : null,
          h("span", { class: "sutil" }, fmtData(i.modificado)))));
      } catch (e) {
        lista.replaceChildren(h("div", { class: "aviso-faixa erro" }, e.message));
      }
    }

    function abrir(i) {
      const tipos = [["resumo", "Resumo"], ["transcricao", "Transcrição"], ["diarizado", "Diarização"], ["log", "Log"]]
        .filter(([k]) => i[k]);
      const texto = h("pre", { class: "texto", tabindex: "0" }, "Carregando…");
      const abasLeitor = h("div", { class: "abas", role: "tablist" });
      let atual = tipos.length ? tipos[0][0] : null;

      async function mostrar(tipo) {
        atual = tipo;
        abasLeitor.replaceChildren(...tipos.map(([k, r]) => h("button", { role: "tab",
          "aria-selected": String(k === atual), onclick: () => mostrar(k) }, r)));
        texto.textContent = "Carregando…";
        try {
          const r = await api(`/api/resultados/${encodeURIComponent(i.nome)}/arquivo?tipo=${tipo}&aba=${aba}`);
          texto.textContent = r.texto + (r.truncado ? "\n\n[arquivo grande: mostrando só o início]" : "");
        } catch (e) { texto.textContent = e.message; }
      }

      leitor.replaceChildren(h("div", { class: "cartao" },
        h("div", { class: "linha" }, h("h2", { style: "margin:0" }, i.nome), h("span", { class: "espaco" }),
          h("button", { onclick: () => api(`/api/resultados/${encodeURIComponent(i.nome)}/abrir-pasta`,
            { method: "POST", corpo: { aba } }).catch((e) => alert(e.message)) }, "Abrir pasta"),
          h("button", { onclick: () => leitor.replaceChildren() }, "Fechar")),
        abasLeitor, texto));
      leitor.scrollIntoView({ behavior: "smooth", block: "start" });
      if (atual) mostrar(atual); else texto.textContent = "Sem arquivos de texto para mostrar.";
    }

    desenharAbas();
    app.replaceChildren(h("h1", {}, "Resultados"),
      h("p", { class: "sub" }, "Reuniões já processadas. Clique para ler o resumo e a transcrição."),
      h("div", { class: "linha", style: "margin-bottom:12px" }, abas, h("span", { class: "espaco" }), campo),
      leitor, lista);
    carregar();
  }

  // ---------------------------------------------------------------- roteador

  function marcarMenu(rota) {
    document.querySelectorAll("#menu a").forEach((a) => a.classList.toggle("atual", a.dataset.rota === rota));
  }

  async function atualizarAtiva() {
    try {
      const r = await api("/api/execucoes");
      const el = document.getElementById("ativa");
      if (r.ativa) {
        el.hidden = false;
        el.href = `#/execucao/${r.ativa}`;
        el.textContent = "Execução em andamento";
      } else {
        el.hidden = true;
      }
    } catch (_) { /* servidor reiniciando */ }
  }

  function rotear() {
    rotaId++;
    limparTimers();
    modalFundo.hidden = true;
    const partes = (location.hash || "#/nova").replace(/^#\//, "").split("/");
    const rota = partes[0] || "nova";
    marcarMenu(rota === "execucao" ? "execucoes" : rota);
    if (rota === "execucao" && partes[1]) viewExecucao(partes[1]);
    else if (rota === "execucoes") viewExecucoes();
    else if (rota === "resultados") viewResultados();
    else viewNova();
    atualizarAtiva();
  }

  async function iniciar() {
    try {
      config = await api("/api/config");
    } catch (e) {
      app.replaceChildren(h("div", { class: "aviso-faixa erro" }, `Não foi possível falar com o servidor: ${e.message}`));
      return;
    }
    window.addEventListener("hashchange", rotear);
    setInterval(atualizarAtiva, 5000);
    rotear();
  }

  iniciar();
})();
