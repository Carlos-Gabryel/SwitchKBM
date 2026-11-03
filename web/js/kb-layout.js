// Teclado da tela do Switch 2, MEDIDO no console real: paginas, grade e regras de navegacao.
// Tudo como dado. "·" = celula sem caractere (navegavel, mas A nao faz nada).
const grid = (...rows) => rows.map((r) => r.split(" ").map((t) => (t === "·" ? null : t)));

export const LAYOUT = {
  name: "Teclado do Switch 2",
  verified: true,
  rows: 4,
  cols: 11,
  start: "r0c0",
  startPage: "abc",
  // lower = sem Shift; upper = com L3 (null: Shift nao muda nada)
  pages: {
    abc: {
      label: "ABC",
      lower: grid("1 2 3 4 5 6 7 8 9 0 =", "q w e r t y u i o p °", "a s d f g h j k l ç ª", "z x c v b n m , . - +"),
      upper: grid('! " # € % & ( ) ? [ ]', "Q W E R T Y U I O P @", "A S D F G H J K L Ç *", "Z X C V B N M ; : _ £"),
    },
    acc1: {
      label: "ÀÁÂ",
      lower: grid("à á â ã ä å æ ā ă ą ç", "ć ċ č ð ď · · è é ê ë", "ē ę ě ğ ġ ģ ħ ì í î ï", "ī į ı · ķ ĺ ļ ľ ł · ·"),
      upper: grid("À Á Â Ã Ä Å Æ Ā Ă Ą Ç", "Ć Ċ Č Ð Ď · · È É Ê Ë", "Ē Ę Ě Ğ Ġ Ģ Ħ Ì Í Î Ï", "Ī Į İ · Ķ Ĺ Ļ Ľ Ł · ·"),
    },
    acc2: {
      label: "ÑŃŅ",
      lower: grid("ñ ń ņ ň ò ó ô õ ö ø œ", "ő ō ŕ ř š ß ś ş þ ť ț", "ù ú û ü ū ů ű ų ý ÿ ź", "ż ž · · · · · · · · ·"),
      upper: grid("Ñ Ń Ņ Ň Ò Ó Ô Õ Ö Ø Œ", "Ő Ō Ŕ Ř Š · Ś Ş Þ Ť Ț", "Ù Ú Û Ü Ū Ů Ű Ų Ý Ÿ Ź", "Ż Ž · · · · · · · · ·"),
    },
    sym: {
      label: "#+=",
      lower: grid("1 2 3 4 5 6 7 8 9 0 -", "! @ # $ % ^ & * ( ) _", "~ ` = \\ + { } | [ ] ·", "< > ; : \" ' , . ? / ·"),
      upper: null,
    },
  },
  // abas, na ordem da linha; a coluna da grade logo acima e o indice. page: aba que troca de pagina
  tabs: [
    { id: "globe", label: "🌐", name: "Idioma" },
    { id: "shift", label: "⇧", name: "Shift" },
    { id: "abc", label: "ABC", name: "ABC", page: "abc" },
    { id: "sym", label: "#+=", name: "#+=", page: "sym" },
    { id: "acc1", label: "ÀÁÂ", name: "ÀÁÂ", page: "acc1" },
    { id: "acc2", label: "ÑŃŅ", name: "ÑŃŅ", page: "acc2" },
  ],
  // coluna direita, por linha da grade
  right: [
    { id: "bksp", label: "⌫", name: "Apagar" },
    { id: "enter1", label: "↵", name: "Enter" },
    { id: "enter2", label: "↵", name: "Enter" },
    { id: "submit3", label: "🔍", name: "Buscar" },
  ],
  // regras do grafo (arestas PROIBIDAS: saem do teclado ou vao para o Espaco)
  rules: {
    noUpFromRow: 0, // r0 + cima vai para as sugestoes
    downFromLastRowOnlyCols: 6, // r3 c0..c5 + baixo vai as abas; c6.. vai ao Espaco (proibido)
  },
  // botoes do CONSOLE (nomes de SWITCH_BTN em typing.js)
  shortcuts: { space: "Y", backspace: "B", submit: "+", shift: "L3" },
};

export const DIRS = ["up", "down", "left", "right"];
export const cellId = (r, c) => `r${r}c${c}`;
const CELL = /^r(\d)c(\d+)$/;
export const parseCell = (id) => {
  const m = CELL.exec(id);
  return m ? { r: +m[1], c: +m[2] } : null;
};
export const PAGE_TAB = Object.fromEntries(LAYOUT.tabs.filter((t) => t.page).map((t) => [t.page, t.id]));

export function allNodes(L = LAYOUT) {
  const out = [];
  for (let r = 0; r < L.rows; r++) for (let c = 0; c < L.cols; c++) out.push(cellId(r, c));
  return out.concat(L.right.map((x) => x.id), L.tabs.map((x) => x.id));
}

// Vizinho de um no na direcao dada (null = aresta que nao existe ou e proibida)
export function nav(node, dir, L = LAYOUT) {
  const cell = parseCell(node);
  if (cell) {
    const { r, c } = cell;
    if (dir === "up") return r > L.rules.noUpFromRow ? cellId(r - 1, c) : null;
    if (dir === "down") {
      if (r < L.rows - 1) return cellId(r + 1, c);
      return c < L.rules.downFromLastRowOnlyCols ? L.tabs[c].id : null;
    }
    const ring = L.cols + 1; // ciclo da linha: c0..c10 + no da coluna direita
    const i = (c + (dir === "right" ? 1 : -1) + ring) % ring;
    return i === L.cols ? L.right[r].id : cellId(r, i);
  }
  const ri = L.right.findIndex((x) => x.id === node);
  if (ri >= 0) {
    if (dir === "up" || dir === "down") return null;
    const ring = L.cols + 1;
    const i = (L.cols + (dir === "right" ? 1 : -1) + ring) % ring;
    return i === L.cols ? node : cellId(ri, i);
  }
  const ti = L.tabs.findIndex((x) => x.id === node);
  if (ti < 0) return null;
  if (dir === "up") return cellId(L.rows - 1, ti);
  if (dir === "down") return null;
  const n = ti + (dir === "right" ? 1 : -1);
  return n >= 0 && n < L.tabs.length ? L.tabs[n].id : null; // sem wrap
}

// BFS a partir de um no: path(to) = lista de direcoes (null se nao alcanca)
export function bfs(from, L = LAYOUT) {
  const prev = new Map([[from, null]]);
  const queue = [from];
  for (let qi = 0; qi < queue.length; qi++) {
    const id = queue[qi];
    for (const d of DIRS) {
      const n = nav(id, d, L);
      if (n === null || prev.has(n)) continue;
      prev.set(n, [id, d]);
      queue.push(n);
    }
  }
  return {
    path(to) {
      if (!prev.has(to)) return null;
      const out = [];
      for (let cur = to; prev.get(cur); cur = prev.get(cur)[0]) out.push(prev.get(cur)[1]);
      return out.reverse();
    },
  };
}

export const shortestPath = (from, to, L = LAYOUT) => bfs(from, L).path(to);
