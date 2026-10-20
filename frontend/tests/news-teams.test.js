import test from 'node:test';
import assert from 'node:assert/strict';
import { filterNewsForTeams, matchesTeams, mentionedTeams } from '../src/lib/news.js';

const ALL = [
  'Arsenal FC', 'Manchester United FC', 'Manchester City FC', 'Tottenham Hotspur FC', 'Sheffield United FC',
  'Nottingham Forest FC', 'FC Barcelona', 'RCD Espanyol de Barcelona', 'Real Madrid CF', 'Club Atlético de Madrid',
  'FC Internazionale Milano', 'AC Milan', 'SSC Napoli', 'Paris Saint-Germain FC', 'Paris FC', 'OGC Nice',
  '1. FC Köln', 'FC Bayern München', 'FC St. Pauli 1910', 'Aston Villa FC', 'Villarreal CF', 'Celtic FC',
];
const mentions = (title, teams = ALL) => mentionedTeams({ title }, teams);

test('canonical names, stripped names and aliases are recognised', () => {
  assert.deepEqual(mentions('Man Utd sign striker'), ['Manchester United FC']);
  assert.deepEqual(mentions('Man United 1-0 Chelsea'), ['Manchester United FC']);
  assert.deepEqual(mentions('Manchester United FC confirm new coach'), ['Manchester United FC']);
  assert.deepEqual(mentions('Spurs boss praises fans'), ['Tottenham Hotspur FC']);
  assert.deepEqual(mentions('Celtic win again'), ['Celtic FC'], 'unknown-alias teams use the stripped name');
  assert.deepEqual(mentions('Bayern Munich stroll to win'), ['FC Bayern München']);
  assert.deepEqual(mentions('Köln and Cologne fans unite'), ['1. FC Köln']);
});

test('both Manchester clubs are told apart; the city alone matches neither', () => {
  assert.deepEqual(mentions('Manchester City 2-1 Manchester United'), ['Manchester United FC', 'Manchester City FC']);
  assert.deepEqual(mentions('Manchester derby preview'), []);
  assert.deepEqual(mentions('City beat United'), []);
  assert.deepEqual(mentions('United are back'), []);
});

test('Milan, Madrid and Paris need the full club name', () => {
  assert.deepEqual(mentions('Inter Milan beat Napoli'), ['FC Internazionale Milano', 'SSC Napoli']);
  assert.deepEqual(mentions('Inter Miami sign veteran'), []);
  assert.deepEqual(mentions('AC Milan held'), ['AC Milan']);
  assert.deepEqual(mentions('Milan derby ends level'), []);
  assert.deepEqual(mentions('Real Madrid v Atletico Madrid'), ['Real Madrid CF', 'Club Atlético de Madrid']);
  assert.deepEqual(mentions('Madrid weather delays kick-off'), []);
  assert.deepEqual(mentions('PSG through to final'), ['Paris Saint-Germain FC']);
  assert.deepEqual(mentions('Paris St-Germain sign forward'), ['Paris Saint-Germain FC']);
  assert.deepEqual(mentions('Paris Saint-Germain v Paris FC'), ['Paris Saint-Germain FC', 'Paris FC']);
});

test('a club inside another club name is not a mention', () => {
  assert.deepEqual(mentions('Espanyol de Barcelona appoint coach'), ['RCD Espanyol de Barcelona']);
  assert.deepEqual(mentions('Barcelona top the table'), ['FC Barcelona']);
  assert.deepEqual(mentions('Villarreal edge Villa'), ['Villarreal CF'], 'whole words only; "Villa" alone is ambiguous');
  assert.deepEqual(mentions('Aston Villa go fourth'), ['Aston Villa FC']);
});

test('lower-case words and sentence nicknames do not count', () => {
  assert.deepEqual(mentions('Saka spurs Arsenal on'), ['Arsenal FC']);
  assert.deepEqual(mentions('Nice goal from the edge of the box'), []);
  assert.deepEqual(mentions('OGC Nice sack coach'), ['OGC Nice']);
  assert.deepEqual(mentions('Sheffield Wednesday promoted'), []);
  assert.deepEqual(mentions('Sheffield United relegated'), ['Sheffield United FC']);
  assert.deepEqual(mentions('Forest fire delays match'), []);
});

test('punctuation and possessives', () => {
  assert.deepEqual(mentions('St. Pauli stun Bayern'), ['FC Bayern München', 'FC St. Pauli 1910']);
  assert.deepEqual(mentions('St Pauli fans'), ['FC St. Pauli 1910']);
  assert.deepEqual(mentions('Nott’m Forest close in'), ['Nottingham Forest FC']);
  assert.deepEqual(mentions("Arsenal's title hopes"), ['Arsenal FC']);
  assert.deepEqual(mentions('ARSENAL WIN'), ['Arsenal FC'], 'upper-case headlines still match');
});

test('only the requested teams are reported, in their given order', () => {
  assert.deepEqual(mentions('Arsenal v Spurs', ['Tottenham Hotspur FC', 'Arsenal FC']), ['Tottenham Hotspur FC', 'Arsenal FC']);
  assert.deepEqual(mentions('Arsenal v Spurs', ['Chelsea FC']), []);
  assert.deepEqual(mentionedTeams({ title: 'Arsenal win' }, []), []);
  assert.deepEqual(mentionedTeams({ title: '' }, ['Arsenal FC']), []);
  assert.deepEqual(mentionedTeams(null, ['Arsenal FC']), []);
  assert.deepEqual(mentionedTeams('Arsenal win', new Set(['Arsenal FC'])), ['Arsenal FC'], 'strings and Sets accepted');
});

test('filterNewsForTeams keeps matching articles in order', () => {
  const articles = [
    { id: 1, title: 'Arsenal win' }, { id: 2, title: 'Manchester derby' }, { id: 3, title: 'Man City sign' },
    { id: 4, title: 'Spurs lose' }, { id: 5 },
  ];
  const teams = ['Arsenal FC', 'Manchester City FC'];
  assert.deepEqual(filterNewsForTeams(articles, teams).map((a) => a.id), [1, 3]);
  assert.equal(matchesTeams(articles[1], teams), false);
  assert.deepEqual(filterNewsForTeams(null, teams), []);
});
