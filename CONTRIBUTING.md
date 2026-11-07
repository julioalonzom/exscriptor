# Contributing

Exscriptor is Apache-2.0. Issues and pull requests are welcome on anything:
a gate that let an error through, a check that cries wolf, a step of the
workflow that should be code instead of judgment, documentation that misled
you. Open an issue if you are not sure; a pull request if you are.

The rest of this file is about the most common contribution: a row in the
spelling list.

## The spelling list

[`src/exscriptor/spelling-map.tsv`](src/exscriptor/spelling-map.tsv) is the
Latin orthography of the Schola Thomistica corpus, applied by code to every
work alike. Three columns, tab-separated: `form`, `edition`, `reason`. The
file's header says exactly how a row is read.

### What a row may do

| Kind | Example | When |
|---|---|---|
| change | `appraeh  appreh  tier 1: false ae …` | a printer's spelling, classicized (below) |
| keep | `humor  humor  keep, tier 2: …` | a scholastic or ecclesiastical spelling a change row would otherwise touch, or a different real word that looks like a misspelling (`precis$`, the genitive of *prex*) |
| pair | `tanquam$\|tamquam$  majority  both legitimate …` | two spellings both legitimate in this literature; each work writes its own majority |

A **change** row classicizes a printer's spelling, by these classes (the
standard is Lewis & Short, the first spelling of the headword, at
[Logeion](https://logeion.uchicago.edu)):

1. a false *ae*, *oe* or *ę* where the word has *e* (*caeterum*, *faetus*,
   *appraehensio*), and *oe* for *ae* or the reverse (*coelum*);
2. a false *h*, *ph* or *y* (*authoritas*, *Peripathetici*, *sylva*), or a
   missing one (*stomacus*, *fantasma*);
3. *e* where the word has *ae* (*presertim*, *sepe*, *adequate*), often an
   unread *ę* in the print;
4. a false *quu* (*quum*, *loquutio*);
5. a medieval spelling the corpus classicizes (*litera*, *nuncius*,
   *diffinitio*, *saltim*).

A form outside these classes is not changed, however odd it looks; a
spelling Lewis & Short also allows (*sequutus* beside *secutus*) is not
changed either. Scholastic and ecclesiastical spellings are kept even where
classical Latin differs (*intelligere*, *conditio*, *poenitentia*,
*obedientia*, *humidus*): they are the authors' own, not their printers'.

### Before you propose a row

- **Search for collisions.** A form is the *beginning* of a word unless it
  ends in `$`. `precis` also begins *precis*, the genitive of *prex*;
  `sepe` also begins *sepes* (hedge) and *sepelio*. Use `$` (whole word),
  a longer form, or a keep row beside the change row. Real forms that look
  like errors catch everyone: *allii* (*allium*, garlic) is not *alii*;
  *ipsammet* is an accusative, not a misspelling of *ipsamet*; *obicem*
  is from *obex*, not *obiicere*.
- **Give the evidence in the reason**: the class, and counts where you have
  them (`corpus presertim 2`, `Mastrius 1757, d. 1: tamquam 24 / tanquam 7`).
- **Run the tests**: `python3 -m pytest tests/test_house.py`. The list must
  parse (a malformed row refuses the whole list), and
  `test_shipped_list_parses_and_guards_the_known_traps` holds the traps
  above; add yours to it.

`python3 -m exscriptor.house candidates --lexicon <your lexicon>` lists
variant pairs a text has both of that the list does not decide yet: a good
place to start (see the README).

### What happens after a merge

The list is versioned with the code: every `expand` record and `preflight`
report names the sha of the list it used. Schola Thomistica re-checks its
published works against a new list and stages the corrections; a row you
add fixes every work that has the form, not only yours.
