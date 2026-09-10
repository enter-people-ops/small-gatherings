"""
Inferência de gênero a partir do PRIMEIRO NOME (nomes brasileiros).

Estratégia:
  1) dicionário curado de nomes comuns (mais confiável);
  2) fallback por terminação (—a => F, —o => M, + exceções masculinas conhecidas).
Retorna "M", "F" ou "?" (quando ambíguo/desconhecido).

RESSALVA: inferência por nome erra em nomes unissex/ambíguos e pode não refletir
a identidade de gênero da pessoa. Usada só para preencher o que falta no Convenia,
como aproximação para equilibrar os grupos — nunca como verdade sobre a pessoa.
"""
from __future__ import annotations
import unicodedata


def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))
    return s.strip().lower()


_FEMALE = {
    "ana","maria","julia","juliana","mariana","marina","fernanda","gabriela","gabrieli","beatriz",
    "amanda","aline","adriana","alessandra","alice","bruna","barbara","bianca","camila","carla",
    "carolina","carol","catarina","cecilia","clara","claudia","cristina","cristiane","daniela","debora",
    "denise","diana","elaine","eliane","elisa","emanuela","emily","erica","ester","fabiana","flavia",
    "geovana","giovana","giovanna","helena","heloisa","ingrid","isabel","isabela","isabella","isadora",
    "jaqueline","jessica","joana","josiane","karen","karina","katia","larissa","laura","leticia",
    "livia","luana","lucia","luciana","luiza","luisa","lais","thais","tais","manuela","marcela",
    "margarida","mariah","marta","mayara","melissa","michele","milena","monica","natalia","nathalia",
    "paula","patricia","paola","priscila","rafaela","raquel","rebeca","renata","roberta","rosa",
    "rosana","sabrina","sandra","sara","sarah","silvia","simone","sofia","sonia","stephanie",
    "tatiane","tatiana","tereza","valentina","vanessa","vera","victoria","vitoria","viviane","yasmin",
    "andressa","bruna","carolina","dandara","dayane","eduarda","francisca","geovanna","heloise",
    "ivana","joyce","kelly","lorena","malu","nayara","olivia","pietra","quezia","regina","suzana",
    "talita","ursula","wanda","yara","zoe","agatha","anna","bella","celia","duda","elisangela",
}

_MALE = {
    "joao","jose","antonio","francisco","carlos","paulo","pedro","lucas","luiz","luis","marcos",
    "gabriel","rafael","daniel","marcelo","bruno","eduardo","felipe","filipe","rodrigo","gustavo",
    "guilherme","andre","fernando","fabio","leonardo","leandro","ricardo","tiago","thiago","vinicius",
    "victor","vitor","matheus","mateus","caio","diego","alex","alexandre","anderson","emerson",
    "wesley","william","willian","robson","rogerio","sergio","henrique","heitor","hugo","igor",
    "ivan","jorge","julio","juliano","kaique","murilo","murillo","nelson","otavio","renan","renato",
    "roberto","samuel","saulo","vagner","wagner","wallace","yuri","adriano","alan","alessandro",
    "arthur","artur","augusto","bernardo","breno","cesar","cezar","cristiano","danilo","davi",
    "david","denis","edson","elias","enzo","erick","fabricio","flavio","geraldo","gilberto",
    "isaac","isaque","joaquim","kevin","leonel","levi","lourenco","marcio","mario","mauricio",
    "miguel","moises","nicolas","noah","otto","ramon","raul","reinaldo","ronaldo","rubens",
    "sandro","sebastiao","valdir","valter","walter","washington","wilson","athos","ettore","hernan",
    "hericles","stefano","rick","michael","aloysio","ademir","alec","murilo","jefferson","cauã","caua",
}

# nomes masculinos que terminam em "a" (exceções à regra da terminação)
_MALE_ENDS_A = {"luca","juca","nicola","joshua","elia","isaias","tobias","dinia","aha"}

# terminações tipicamente masculinas (fallback)
_MALE_SUFFIXES = ("o","el","il","ol","ul","or","ir","ur","son","ton","son","son","im","az","uz",
                  "os","us","au","ao","dro","que","nir","mar","zar","ael","iel","uel")


def infer_gender(full_name: str) -> str:
    """Retorna 'M', 'F' ou '?' a partir do primeiro nome."""
    if not full_name:
        return "?"
    first = _norm(full_name).split()[0] if _norm(full_name).split() else ""
    if not first:
        return "?"
    if first in _FEMALE:
        return "F"
    if first in _MALE:
        return "M"
    # fallback por terminação
    if first in _MALE_ENDS_A:
        return "M"
    if first.endswith("a"):
        return "F"
    for suf in _MALE_SUFFIXES:
        if first.endswith(suf):
            return "M"
    if first.endswith("e"):   # ambíguo em PT (Alexandre M / Adriane F) -> desconhecido
        return "?"
    return "?"


def fill_gender(gender_raw: str, name: str) -> str:
    """Mantém o gênero real do Convenia; se vazio/desconhecido, infere pelo nome."""
    g = (gender_raw or "").strip()
    if g and g not in ("?", "N/D"):
        return g
    return infer_gender(name)
