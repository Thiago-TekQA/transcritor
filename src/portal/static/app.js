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
      selParados: new Set(),
      vistos: new Set(),
      vistosP: new Set(),
      analisando: false,
      concorrentes: null,
    };

    const campoPasta = h("input", {
      type: "text", class: "campo-pasta", value: est.origem,
      placeholder: "Caminho da pasta com os vídeos/áudios (ex.: D:\\Reunioes)",
      "aria-label": "Pasta de origem",
    });
    const areaPlano = h("div", {});
    const areaAvisos = h("div", {});
    const areaOcultos = h("div", {});
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
      if (!est.etapas.size) { areaPlano.replaceChildren(h("div", { class: "aviso-faixa erro" }, "Selecione ao menos uma etapa.")); return; }
      est.analisando = true;
      if (est.origem) areaPlano.replaceChildren(h("div", { class: "vazio" }, "Analisando a pasta…"));
      const pedir = (origem) => api("/api/plano", { method: "POST", corpo: {
        origem, etapas: [...est.etapas], recursivo: est.recursivo } });
      let plano = null;
      let erroOrigem = null;
      try {
        try {
          plano = await pedir(est.origem);
        } catch (e) {
          if (!est.origem) throw e;
          // a pasta informada não serve, mas os itens parados ainda aparecem
          erroOrigem = e.message;
          plano = await pedir("");
        }
        if (minhaRota !== rotaId) return;
        if (est.origem && !erroOrigem) localStorage.setItem("ultima_origem", est.origem);
        const anterior = est.sel, anteriorP = est.selParados;
        est.plano = plano;
        est.erroOrigem = erroOrigem;
        // item novo na lista nasce marcado; o que o usuário já desmarcou continua desmarcado
        est.sel = new Set(plano.itens.filter((i) => !i.excluido && (!est.vistos.has(i.nome) || anterior.has(i.nome))).map((i) => i.nome));
        // parados NÃO vêm marcados: o usuário escolhe o que continua
        est.selParados = new Set(plano.parados.filter((i) => est.vistosP.has(i.nome) && anteriorP.has(i.nome)).map((i) => i.nome));
        plano.itens.forEach((i) => est.vistos.add(i.nome));
        plano.parados.forEach((i) => est.vistosP.add(i.nome));
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

    function textoParou(i) {
      const p = i.parou;
      if (!p) return "Sem registro de execução (os arquivos já estavam na área de trabalho).";
      const quando = fmtData(p.criado);
      const e = p.etapa ? rotulo(p.etapa) : "";
      const motivo = p.motivo ? ` — ${p.motivo}` : "";
      switch (p.estado) {
        case "cancelado": return `Interrompido na etapa ${e} (${quando})`;
        case "falhou": return `Falhou na etapa ${e}${motivo} (${quando})`;
        case "aguardando_cpu": case "rodando": return `Parou durante a etapa ${e} (${quando})`;
        case "ok": return `A última execução (${quando}) fez só: ${(p.etapas || []).map(rotulo).join(", ")} — faltam as demais etapas`;
        default: return `Não chegou a executar a etapa ${e} (${quando})`;
      }
    }

    async function chamar(caminho, corpo) {
      try {
        return await api(caminho, { method: "POST", corpo });
      } catch (e) { alert(e.message); return null; }
    }

    async function removerDaLista(i) {
      await chamar(`/api/parados/${encodeURIComponent(i.nome)}/ocultar`);
      est.selParados.delete(i.nome);
      analisar();
    }

    async function restaurar(i) {
      await chamar(`/api/parados/${encodeURIComponent(i.nome)}/restaurar`);
      await analisar();
      if (areaOcultos.childNodes.length) mostrarOcultos();
    }

    async function deletarArquivos(i) {
      let arqs;
      try {
        arqs = (await api(`/api/parados/${encodeURIComponent(i.nome)}/arquivos`)).arquivos;
      } catch (e) { alert(e.message); return; }
      if (!arqs.length) { alert("Este item não tem arquivos na área de trabalho."); return; }
      const total = arqs.reduce((a, x) => a + x.tamanho, 0);
      const lista = arqs.map((x) => `• ${x.pasta}\\${x.arquivo} (${fmtTam(x.tamanho)})`).join("\n");
      if (!confirm(`Deletar ${arqs.length} arquivo(s) de "${i.nome}" (${fmtTam(total)})?\n\n${lista}\n\n` +
        "Isso não pode ser desfeito. A sua pasta de origem NÃO é tocada.")) return;
      const r = await chamar(`/api/parados/${encodeURIComponent(i.nome)}/deletar`, { confirmar: true });
      if (r && r.falhas && r.falhas.length) alert("Alguns arquivos não puderam ser apagados:\n" + r.falhas.join("\n"));
      est.selParados.delete(i.nome);
      await analisar();
      if (areaOcultos.childNodes.length) mostrarOcultos();
    }

    async function mostrarOcultos() {
      let itens;
      try {
        itens = (await api("/api/parados/ocultos")).itens;
      } catch (e) { alert(e.message); return; }
      if (!itens.length) { areaOcultos.replaceChildren(); return; }
      areaOcultos.replaceChildren(h("div", { class: "cartao" },
        h("div", { class: "linha", style: "margin-bottom:8px" }, h("h2", { style: "margin:0" }, `Itens ocultos da lista (${itens.length})`),
          h("span", { class: "espaco" }), h("button", { onclick: () => areaOcultos.replaceChildren() }, "Fechar")),
        h("table", {}, h("tbody", {}, itens.map((i) => h("tr", {},
          h("td", { class: "nome" }, i.nome, h("div", { class: "sutil" }, `Já tem: ${i.feitas.join(", ") || "—"}`)),
          h("td", {}, h("div", { class: "linha" },
            h("button", { onclick: () => restaurar(i) }, "Voltar para a lista"),
            h("button", { class: "perigo", onclick: () => deletarArquivos(i) }, "Deletar arquivos")))))))));
    }

    function linkOcultos(p) {
      return p.n_ocultos ? h("div", { class: "sutil", style: "margin-bottom:12px" },
        `${p.n_ocultos} item(ns) oculto(s) da lista de parados · `,
        h("a", { href: "#", onclick: (ev) => { ev.preventDefault(); mostrarOcultos(); } }, "mostrar")) : null;
    }

    function desenharPlano() {
      const p = est.plano;
      const parados = p.parados || [];

      if (!p.itens.length && !parados.length) {
        trocar(areaPlano, est.erroOrigem ? h("div", { class: "aviso-faixa erro" }, est.erroOrigem) : null,
          linkOcultos(p),
          est.origem && !est.erroOrigem ? h("div", { class: "cartao vazio" }, "Nenhum arquivo de áudio ou vídeo encontrado nesta pasta.")
            : h("div", { class: "cartao vazio" }, "Informe a pasta com os vídeos/áudios e clique em Analisar."));
        return;
      }

      const escolhidos = p.itens.filter((i) => est.sel.has(i.nome));
      const parSel = parados.filter((i) => est.selParados.has(i.nome));
      const todosSel = [...escolhidos, ...parSel];
      const bloqueados = todosSel.flatMap((i) => Object.entries(i.estagios)
        .filter(([, s]) => s.acao === "bloqueado").map(([e, s]) => ({ item: i.nome, etapa: e, ...s })));
      const copiar = escolhidos.filter((i) => i.copiar).reduce((a, i) => a + i.tamanho, 0);
      const algoParaFazer = todosSel.some((i) => Object.values(i.estagios).some((s) => s.acao === "executar"));

      const celulasEtapas = (i) => p.etapas.map((e) => {
        const s = i.estagios[e];
        return h("td", { class: "celula" }, textoAcao(s),
          s.motivo ? h("span", { class: "sutil detalhe" }, s.motivo) : null);
      });

      // ---- itens parados no meio do caminho
      let cartaoParados = null;
      if (parados.length) {
        const todosP = h("input", { type: "checkbox", "aria-label": "Selecionar todos os parados" });
        todosP.checked = parados.every((i) => est.selParados.has(i.nome));
        todosP.addEventListener("change", () => {
          est.selParados = new Set(todosP.checked ? parados.map((i) => i.nome) : []);
          desenharPlano();
        });
        const linhasP = parados.map((i) => {
          const chk = h("input", { type: "checkbox", "aria-label": `Continuar ${i.nome}` });
          chk.checked = est.selParados.has(i.nome);
          chk.addEventListener("change", () => {
            if (chk.checked) est.selParados.add(i.nome); else est.selParados.delete(i.nome);
            desenharPlano();
          });
          return h("tr", {}, h("td", {}, chk),
            h("td", { class: "nome" }, i.nome,
              h("div", { class: "sutil" }, `Já tem: ${i.feitas.join(", ") || "—"}`),
              h("div", { class: "sutil" }, textoParou(i), i.parou ? " · " : "",
                i.parou ? h("a", { href: `#/execucao/${i.parou.run}` }, "ver execução") : null)),
            h("td", { class: "sutil" }, fmtData(i.modificado)),
            ...celulasEtapas(i),
            h("td", {}, h("div", { class: "linha", style: "flex-wrap:nowrap" },
              h("button", { title: "Esconde o item da lista; os arquivos ficam", onclick: () => removerDaLista(i) }, "Remover da lista"),
              h("button", { class: "perigo", title: "Apaga os arquivos intermediários deste item", onclick: () => deletarArquivos(i) }, "Deletar arquivos"))));
        });
        cartaoParados = h("div", { class: "cartao" },
          h("div", { class: "linha", style: "margin-bottom:6px" },
            h("h2", { style: "margin:0" }, `Parados no meio do caminho (${parados.length})`)),
          h("p", { class: "sub", style: "margin:0 0 10px" },
            "Estes itens já estão na área de trabalho e não foram concluídos. Marque os que devem continuar (o que já foi feito não é refeito). Remover da lista só esconde o item; Deletar arquivos apaga os arquivos intermediários dele."),
          h("div", { class: "tabela-rolagem" }, h("table", {},
            h("thead", {}, h("tr", {}, h("th", {}, todosP), h("th", {}, "Item"), h("th", {}, "Última atividade"),
              ...p.etapas.map((e) => h("th", {}, rotulo(e))), h("th", {}, ""))),
            h("tbody", {}, linhasP))));
      }

      // ---- arquivos da pasta de origem
      let cartaoOrigem = null;
      if (p.itens.length) {
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
            h("td", { class: "tam" }, fmtTam(i.tamanho)), ...celulasEtapas(i),
            h("td", { class: "sutil" }, i.copiar ? `Copiar para ${i.copiar.area}` : "—"));
        });
        cartaoOrigem = h("div", { class: "cartao" },
          h("h2", {}, `${p.itens.length} arquivo(s) na pasta`),
          h("div", { class: "tabela-rolagem" }, h("table", {}, h("thead", {}, cab), h("tbody", {}, linhas))));
      }

      const sugeridas = [...new Set(bloqueados.map((b) => b.sugerir).filter(Boolean))];

      const iniciar = h("button", { class: "primario", disabled: !todosSel.length || bloqueados.length > 0 || !algoParaFazer,
        onclick: async () => {
          if (est.concorrentes && !confirm(
            `Já há ${est.concorrentes} pipeline(s) rodando neste computador. Uma nova execução vai disputar a GPU e a memória com ela(s) ` +
            "(mais lenta e mais sujeita a falhas). Iniciar mesmo assim?\n\nDica: a tela Processos mostra e permite encerrar o que estiver sobrando.")) return;
          iniciar.disabled = true;
          try {
            const r = await api("/api/execucoes", { method: "POST", corpo: {
              origem: p.origem, etapas: p.etapas, itens: [...est.sel, ...est.selParados], recursivo: est.recursivo } });
            location.hash = `#/execucao/${r.id}`;
          } catch (e) {
            alert(e.message);
            iniciar.disabled = false;
          }
        } }, "Iniciar execução");

      trocar(areaPlano,
        est.erroOrigem ? h("div", { class: "aviso-faixa erro" }, `${est.erroOrigem} — mostrando só os itens já na área de trabalho.`) : null,
        bloqueados.length ? h("div", { class: "aviso-faixa erro" },
          `${bloqueados.length} etapa(s) bloqueada(s) nos itens selecionados (falta algo de uma etapa anterior). `,
          sugeridas.length ? h("button", { onclick: () => {
            sugeridas.forEach((e) => est.etapas.add(e));
            desenharControles();
            analisar();
          } }, `Marcar: ${sugeridas.map(rotulo).join(", ")}`) : null) : null,
        todosSel.length && !algoParaFazer && !bloqueados.length
          ? h("div", { class: "aviso-faixa info" }, "Tudo isto já existe na área de trabalho — não há nada a fazer.") : null,
        h("div", { class: "cartao" }, h("div", { class: "linha" },
          h("strong", {}, `${todosSel.length} item(ns) selecionado(s)`),
          h("span", { class: "sutil" },
            (parSel.length ? `${parSel.length} continuando` : "") +
            (parSel.length && escolhidos.length ? " · " : "") +
            (escolhidos.length ? `${escolhidos.length} da pasta` : "") +
            (copiar ? ` · copiar ${fmtTam(copiar)} para a área de trabalho` : "")),
          h("span", { class: "espaco" }), iniciar)),
        cartaoParados, linkOcultos(p), cartaoOrigem);
    }

    desenharControles();

    trocar(app,
      h("h1", {}, "Nova execução"),
      h("p", { class: "sub" }, "Aponte uma pasta, escolha as etapas e acompanhe cada arquivo. A pasta de origem nunca é alterada: os arquivos são copiados para a área de trabalho."),
      config.modelo_em_cache ? null : h("div", { class: "aviso-faixa" },
        `O modelo de transcrição "${config.modelo_whisper}" ainda não está neste computador: ele será baixado da internet na primeira transcrição (~500 MB). ` +
        "Se a rede bloquear (erro de certificado), ", h("a", { href: "#/ambiente" }, "abra a tela Ambiente"), " para verificar e corrigir (certificados, download ou importação do modelo)."),
      areaAvisos,
      h("div", { class: "cartao" },
        h("h2", {}, "1. Pasta de origem"),
        h("div", { class: "linha" }, campoPasta,
          h("button", { onclick: () => abrirModalPastas(campoPasta.value.trim(), (c) => { campoPasta.value = c; est.origem = c; analisar(); }) }, "Procurar…"),
          h("label", { class: "opcao" }, chkSub, "Incluir subpastas"),
          h("button", { class: "primario", onclick: analisar }, "Analisar"))),
      h("div", { class: "cartao" },
        h("h2", {}, "2. O que executar"), areaPresets, areaEtapas),
      areaPlano,
      areaOcultos,
    );

    async function verificarConcorrencia() {
      try {
        const m = await api("/api/processos");
        if (minhaRota !== rotaId) return;
        est.concorrentes = m.pipelines_ativos || 0;
        const avisos = [];
        if (m.pipelines_ativos) {
          avisos.push(h("div", { class: "aviso-faixa" },
            `Já há ${m.pipelines_ativos} pipeline(s) rodando neste computador (podem ser de outra instalação). Iniciar outra execução vai disputar a GPU e a memória. `,
            h("a", { href: "#/processos" }, "Ver processos")));
        }
        if (m.orfaos) {
          avisos.push(h("div", { class: "aviso-faixa" },
            `${m.orfaos} processo(s) do Ollama órfãos estão ocupando memória à toa. `,
            h("a", { href: "#/processos" }, "Ver e encerrar")));
        }
        trocar(areaAvisos, ...avisos);
      } catch (_) { /* sem mapeamento: segue sem aviso */ }
    }

    analisar();
    verificarConcorrencia();
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
            h("p", { class: "sub" }, s.origem || "Itens já na área de trabalho", " · ", s.etapas.map(rotulo).join(" → "),
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
      if (s.limpezas && s.limpezas.length) {
        const porEtapa = {};
        s.limpezas.forEach((l) => { (porEtapa[l.etapa] = porEtapa[l.etapa] || []).push(l.nome); });
        f.push(h("div", { class: "aviso-faixa info" },
          "Limpeza após interrupção: " +
          Object.entries(porEtapa).map(([e, ns]) => `${e === "copiar" ? "cópia" : rotulo(e)} (${ns.join(", ")})`).join("; ") +
          " — só a saída parcial dessa etapa foi removida; vídeo e áudio foram mantidos."));
      }
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
          h("td", { class: "nome" }, x.origem || "Itens já na área de trabalho"),
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
    const controles = h("div", { class: "linha", style: "margin-bottom:12px" }, abas, h("span", { class: "espaco" }), campo);
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

      // Lista -> detalhe: ao abrir uma reunião, a lista e os filtros somem
      // (senão o item apareceria duas vezes: aberto em cima e listado embaixo).
      controles.hidden = true;
      lista.hidden = true;
      leitor.replaceChildren(h("div", { class: "cartao" },
        h("div", { class: "linha" },
          h("button", { onclick: voltar }, "← Voltar para a lista"),
          h("h2", { style: "margin:0" }, i.nome), h("span", { class: "espaco" }),
          h("button", { onclick: () => api(`/api/resultados/${encodeURIComponent(i.nome)}/abrir-pasta`,
            { method: "POST", corpo: { aba } }).catch((e) => alert(e.message)) }, "Abrir pasta")),
        abasLeitor, texto));
      window.scrollTo(0, 0);
      if (atual) mostrar(atual); else texto.textContent = "Sem arquivos de texto para mostrar.";
    }

    function voltar() {
      leitor.replaceChildren();
      controles.hidden = false;
      lista.hidden = false;
    }

    desenharAbas();
    app.replaceChildren(h("h1", {}, "Resultados"),
      h("p", { class: "sub" }, "Reuniões já processadas. Clique para ler o resumo e a transcrição."),
      controles, leitor, lista);
    carregar();
  }

  // ---------------------------------------------------------------- Ambiente

  function viewAmbiente() {
    const minhaRota = rotaId;
    const corpo = h("div", {});
    const painelTarefa = h("div", {});
    const campoZip = h("input", { type: "text", class: "campo-pasta",
      placeholder: "Caminho do arquivo modelo_small.zip (ex.: C:\\Users\\voce\\Downloads\\modelo_small.zip)",
      "aria-label": "Arquivo do modelo" });
    let diag = null;
    let tarefaAnterior = null;

    app.replaceChildren(h("h1", {}, "Ambiente"),
      h("p", { class: "sub" }, "Verifica o que o transcritor precisa neste computador e corrige o que faltar."),
      corpo, painelTarefa);

    async function pedir(acao, caminho) {
      try {
        await api("/api/ambiente/acao", { method: "POST", corpo: { acao, caminho } });
        acompanhar();
      } catch (e) { alert(e.message); }
    }

    function linha(estado, titulo, detalhe, ...botoes) {
      const [rot, tipo] = { ok: ["OK", "ok"], falta: ["Falta", "erro"], atencao: ["Atenção", "aviso"], info: ["Info", ""] }[estado];
      return h("tr", {}, h("td", {}, pilula(rot, tipo)), h("td", { class: "nome" }, titulo,
        detalhe ? h("div", { class: "sutil" }, detalhe) : null),
        h("td", {}, h("div", { class: "linha" }, ...botoes.filter(Boolean))));
    }

    function desenhar() {
      if (!diag) return;
      if (diag.erro) {
        corpo.replaceChildren(h("div", { class: "aviso-faixa erro" }, `Não foi possível verificar: ${diag.erro}`));
        return;
      }
      const ocupado = !!tarefaAnterior && tarefaAnterior.estado === "rodando";
      const hf = diag.huggingface, m = diag.modelo, o = diag.ollama;

      const btn = (texto, acao) => h("button", { disabled: ocupado, onclick: () => pedir(acao) }, texto);

      const linhas = [
        linha(diag.ffmpeg ? "ok" : "falta", "FFmpeg (extrai o áudio dos vídeos)",
          diag.ffmpeg ? "" : "Instale com: winget install Gyan.FFmpeg — depois feche e reabra o portal."),
        linha(diag.pip_system_certs ? "ok" : (hf.ok ? "info" : "falta"), "Certificados do Windows no Python",
          diag.pip_system_certs ? `pip-system-certs ${diag.pip_system_certs}` :
            "Faz o Python confiar no certificado do antivírus/empresa (necessário quando o antivírus inspeciona o HTTPS).",
          diag.pip_system_certs ? null : btn("Instalar suporte a certificados", "instalar_certs")),
        linha(hf.ok ? "ok" : "falta", "Acesso ao Hugging Face (baixar o modelo)",
          hf.ok ? "Conexão normal." :
            hf.ssl ? `Bloqueado por certificado não confiável — assinado por: ${hf.emissor}. ` +
              "Instale o suporte a certificados acima; se continuar, informe o certificado raiz em config.json (ca_bundle) ou importe o modelo de um arquivo."
              : `Sem acesso: ${hf.erro}`),
        linha(m.em_cache ? "ok" : "falta", `Modelo de transcrição "${m.nome}"`,
          m.em_cache ? `Já está neste computador (${m.pasta}) — transcreve sem internet.` : "Ainda não está neste computador (~500 MB).",
          m.em_cache ? null : btn("Baixar agora", "baixar_modelo")),
        m.em_cache ? null : h("tr", {}, h("td", {}), h("td", { class: "nome" }, "Ou importe de um arquivo",
          h("div", { class: "sutil" }, "Gere o .zip em outro computador com: python transferir_modelo.py exportar " + m.nome)),
          h("td", {}, h("div", { class: "linha" }, campoZip,
            h("button", { disabled: ocupado, onclick: () => pedir("importar_modelo", campoZip.value) }, "Importar")))),
        linha(o.instalado && o.tem_modelo ? "ok" : (o.instalado ? "atencao" : "falta"), `Ollama e modelo de resumo "${o.modelo_alvo}"`,
          !o.instalado ? "Ollama não está instalado: winget install Ollama.Ollama" :
            o.tem_modelo ? (o.rodando ? "Pronto." : "Pronto — o Ollama é ligado automaticamente na etapa de resumo.") :
              "Falta baixar o modelo do resumo (~2 GB).",
          o.instalado && !o.tem_modelo ? btn("Baixar modelo do resumo", "baixar_ollama") : null),
        linha(diag.layout.legado ? "atencao" : "ok", "Pastas de trabalho",
          diag.layout.legado
            ? "Estão direto na raiz do projeto (layout antigo), misturadas com os arquivos do programa. Para organizar em dados/: feche o portal e execute ferramentas\\Migrar_para_dados.bat."
            : `Organizadas em ${diag.layout.base_dir}`),
        linha("info", "Python", `${diag.python}${diag.venv ? " (ambiente virtual)" : ""} — ${diag.executavel}`),
      ].filter(Boolean);

      corpo.replaceChildren(h("div", { class: "cartao" },
        h("div", { class: "linha", style: "margin-bottom:10px" }, h("h2", { style: "margin:0" }, "Verificações"),
          h("span", { class: "espaco" }), h("button", { disabled: ocupado, onclick: verificar }, "Verificar de novo")),
        h("div", { class: "tabela-rolagem" }, h("table", {}, h("tbody", {}, linhas)))));
    }

    async function verificar() {
      corpo.replaceChildren(h("div", { class: "vazio" }, "Verificando… (pode levar alguns segundos)"));
      try {
        diag = await api("/api/ambiente");
      } catch (e) { diag = { erro: e.message }; }
      if (minhaRota !== rotaId) return;
      desenhar();
    }

    async function acompanhar() {
      if (minhaRota !== rotaId) return;
      let t;
      try { t = await api("/api/ambiente/tarefa"); } catch (_) { timers.push(setTimeout(acompanhar, 2000)); return; }
      if (minhaRota !== rotaId) return;
      const terminou = !!tarefaAnterior && tarefaAnterior.estado === "rodando" && t.estado !== "rodando";
      tarefaAnterior = t;
      if (t.estado === "ocioso") { painelTarefa.replaceChildren(); desenhar(); return; }
      const rot = { rodando: ["Em andamento", "rodando"], ok: ["Concluído", "ok"], erro: ["Falhou", "erro"] }[t.estado];
      const pre = h("pre", { class: "log" }, t.texto || "…");
      painelTarefa.replaceChildren(h("div", { class: "cartao" }, h("div", { class: "linha", style: "margin-bottom:10px" },
        h("h2", { style: "margin:0" }, `Correção: ${t.acao}`), pilula(rot[0], rot[1])), pre));
      pre.scrollTop = pre.scrollHeight;
      if (t.estado === "rodando") { desenhar(); timers.push(setTimeout(acompanhar, 1000)); }
      else if (terminou) verificar();
      else desenhar();
    }

    verificar();
    acompanhar();
  }

  // ---------------------------------------------------------------- Processos

  function haQuanto(epoch) {
    const s = Math.max(0, Math.round(Date.now() / 1000 - epoch));
    return s < 60 ? `${s}s` : fmtDur(s);
  }

  function viewProcessos() {
    const minhaRota = rotaId;
    const corpo = h("div", {});

    app.replaceChildren(h("h1", {}, "Processos"),
      h("p", { class: "sub" }, "Tudo o que o transcritor está rodando neste computador — inclusive de outras instalações ou cópias do projeto. Dois pipelines ao mesmo tempo disputam a GPU e causam lentidão e falhas."),
      corpo);

    function textoConfirmacao(r) {
      if (r.tipo === "pipeline" && r.execucao) {
        return `Cancelar a execução ${r.execucao}? O arquivo em andamento será interrompido (só a saída parcial dessa etapa é descartada; vídeo e áudio ficam).`;
      }
      if (r.tipo === "pipeline") {
        return `Encerrar o pipeline (PID ${r.pid}) de OUTRA instalação${r.local ? ` (${r.local})` : ""}?\n\nO que ele está processando ficará incompleto: arquivos parciais na pasta dele, descartados na próxima execução dela.`;
      }
      if (r.tipo === "ollama" && r.orfao) {
        return `Encerrar este processo órfão do Ollama (PID ${r.pid}, ${r.ram_mb} MB)? Nenhum servidor o usa.`;
      }
      if (r.tipo === "ollama") {
        return "Encerrar o Ollama? Qualquer resumo em andamento vai falhar (o pipeline liga o Ollama de novo quando precisar).";
      }
      return `Encerrar ${r.rotulo} (PID ${r.pid}) e os processos filhos dele?`;
    }

    async function encerrar(r) {
      if (!confirm(textoConfirmacao(r))) return;
      try {
        const resp = await api(`/api/processos/${r.pid}/encerrar`, { method: "POST", corpo: { confirmar: true } });
        alert(resp.mensagem);
      } catch (e) { alert(e.message); }
      carregar(true);
    }

    async function encerrarOrfaos(lista) {
      const gb = (lista.reduce((a, r) => a + r.ram_mb, 0) / 1024).toFixed(1);
      if (!confirm(`Encerrar ${lista.length} processo(s) órfão(s) do Ollama (~${gb} GB de RAM)? Nenhum servidor os usa.`)) return;
      for (const r of lista) {
        try { await api(`/api/processos/${r.pid}/encerrar`, { method: "POST", corpo: { confirmar: true } }); } catch (_) { /* segue */ }
      }
      carregar(true);
    }

    function linhas(raizes, nivel, saida) {
      for (const r of raizes) {
        saida.push([r, nivel]);
        linhas(r.filhos, nivel + 1, saida);
      }
      return saida;
    }

    function desenhar(m) {
      const todos = linhas(m.raizes, 0, []);
      const orfaos = todos.map(([r]) => r).filter((r) => r.orfao);

      const gpu = m.gpu ? h("div", { class: "cartao" }, h("div", { class: "resumo-contagem" },
        h("div", {}, h("strong", {}, m.gpu.nome), h("span", {}, "placa de vídeo")),
        h("div", {}, h("strong", {}, `${m.gpu.uso_pct}%`), h("span", {}, "uso da GPU")),
        h("div", {}, h("strong", {}, `${m.gpu.temp_c} °C`), h("span", {}, "temperatura")),
        h("div", {}, h("strong", {}, `${(m.gpu.mem_usada_mb / 1024).toFixed(1)} / ${(m.gpu.mem_total_mb / 1024).toFixed(1)} GB`), h("span", {}, "memória da GPU")),
        h("div", {}, h("strong", {}, String(m.pipelines_ativos)), h("span", {}, "pipelines ativos")))) : null;

      const faixas = m.alertas.map((a) => h("div", { class: "aviso-faixa" }, a));

      const tabela = todos.length ? h("div", { class: "cartao" },
        h("div", { class: "linha", style: "margin-bottom:10px" }, h("h2", { style: "margin:0" }, "Processos do transcritor"),
          h("span", { class: "espaco" }),
          orfaos.length ? h("button", { onclick: () => encerrarOrfaos(orfaos) }, `Encerrar ${orfaos.length} órfão(s) do Ollama`) : null,
          h("button", { onclick: () => carregar(true) }, "Atualizar")),
        h("div", { class: "tabela-rolagem" }, h("table", {},
          h("thead", {}, h("tr", {}, ["Processo", "PID", "Onde", "Rodando há", "CPU", "RAM", ""].map((t) => h("th", {}, t)))),
          h("tbody", {}, todos.map(([r, nivel]) => h("tr", {},
            h("td", { class: "nome" }, h("span", { style: `margin-left:${nivel * 22}px` }, nivel ? "└ " : ""), r.rotulo + " ",
              r.orfao ? pilula("órfão", "erro") : null, r.proprio ? pilula("este portal", "info") : null,
              r.execucao ? pilula("execução do portal", "info") : null,
              h("div", { class: "sutil", title: r.comando, style: `margin-left:${nivel * 22}px` }, r.comando.length > 90 ? r.comando.slice(0, 90) + "…" : r.comando)),
            h("td", { class: "num" }, String(r.pid)),
            h("td", { class: "sutil" }, !r.local ? "—" : r.desta_instalacao ? "esta instalação" : `OUTRA: ${r.local}`),
            h("td", { class: "num" }, haQuanto(r.inicio)),
            h("td", { class: "num" }, fmtDur(r.cpu_s)),
            h("td", { class: "num" }, `${r.ram_mb} MB`),
            h("td", {}, r.proprio || r.protegido ? null :
              h("button", { class: "perigo", onclick: () => encerrar(r) }, r.tipo === "pipeline" && r.execucao ? "Cancelar execução" : "Encerrar")))))))
      ) : h("div", { class: "cartao vazio" }, "Nenhum processo do transcritor em execução.");

      trocar(corpo, gpu, ...faixas, tabela);
    }

    async function carregar(forcar) {
      if (minhaRota !== rotaId) return;
      try {
        const m = await api("/api/processos");
        if (minhaRota !== rotaId) return;
        desenhar(m);
      } catch (e) {
        corpo.replaceChildren(h("div", { class: "aviso-faixa erro" }, e.message));
      }
      if (!forcar && minhaRota === rotaId) timers.push(setTimeout(carregar, 4000));
    }

    corpo.replaceChildren(h("div", { class: "vazio" }, "Mapeando processos…"));
    carregar();
  }

  // ---------------------------------------------------------------- roteador

  function marcarMenu(rota) {
    document.querySelectorAll("#menu a").forEach((a) => a.classList.toggle("atual", a.dataset.rota === rota));
  }

  let encerrado = false;     // portal desligado pelo botão: a página para de consultar

  async function encerrarPortal() {
    let ativa = false;
    try { ativa = !!(await api("/api/execucoes")).ativa; } catch (_) { /* decide sem saber */ }
    const pergunta = ativa
      ? "Encerrar o portal?\n\nA execução em andamento continua em segundo plano. Para acompanhar, abra o Transcritor de novo."
      : "Encerrar o portal?\n\nPara usar de novo, abra o Transcritor.";
    if (!confirm(pergunta)) return;
    try {
      await api("/api/encerrar", { method: "POST" });
    } catch (e) {
      alert(`Não foi possível encerrar o portal: ${e.message}`);
      return;
    }
    encerrado = true;
    rotaId++;
    limparTimers();
    modalFundo.hidden = true;
    document.getElementById("menu").hidden = true;
    document.getElementById("ativa").hidden = true;
    document.getElementById("encerrar").hidden = true;
    trocar(app, h("div", { class: "cartao vazio" },
      h("h2", { texto: "Portal encerrado" }),
      h("p", { texto: ativa
        ? "A execução em andamento continua em segundo plano. Pode fechar esta aba; para acompanhar, abra o Transcritor de novo."
        : "Pode fechar esta aba. Para usar de novo, abra o Transcritor." })));
  }

  async function atualizarAtiva() {
    if (encerrado) return;
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
    if (encerrado) return;
    rotaId++;
    limparTimers();
    modalFundo.hidden = true;
    const partes = (location.hash || "#/nova").replace(/^#\//, "").split("/");
    const rota = partes[0] || "nova";
    marcarMenu(rota === "execucao" ? "execucoes" : rota);
    if (rota === "execucao" && partes[1]) viewExecucao(partes[1]);
    else if (rota === "execucoes") viewExecucoes();
    else if (rota === "resultados") viewResultados();
    else if (rota === "ambiente") viewAmbiente();
    else if (rota === "processos") viewProcessos();
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
    document.getElementById("encerrar").addEventListener("click", encerrarPortal);
    setInterval(atualizarAtiva, 5000);
    rotear();
  }

  iniciar();
})();
