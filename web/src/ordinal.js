// "1st"/"2nd"/"3rd"/"4th"... — used to show each seat's actual turn-order
// position (seat 0 goes first, seat 1 second, ...), which stopped being
// guessable once solo mode started shuffling who sits where (see
// main.py's _run_solo). Century only ever has 2-5 seats, but this handles
// any n correctly (the 11th/12th/13th exception band included).
export function ordinal(n) {
  const v = n % 100
  if (v >= 11 && v <= 13) return `${n}th`
  switch (n % 10) {
    case 1:
      return `${n}st`
    case 2:
      return `${n}nd`
    case 3:
      return `${n}rd`
    default:
      return `${n}th`
  }
}
