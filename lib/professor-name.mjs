function maskPart(part) {
  const characters = Array.from(part);
  if (characters.length <= 1) return part;
  if (characters.length === 2) return `${characters[0]}○`;
  return `${characters[0]}${'○'.repeat(characters.length - 2)}${characters.at(-1)}`;
}

export function maskProfessorName(name) {
  if (typeof name !== 'string') return '';
  return name.trim().split(/(\s+)/u).map((part) => /^\s+$/u.test(part) ? part : maskPart(part)).join('');
}
