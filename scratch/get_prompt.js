const fs = require('fs');
const readline = require('readline');

async function main() {
  const fileStream = fs.createReadStream('C:/Users/TTD/.gemini/antigravity/brain/76e43c54-2a95-4105-8066-69e53cbabdc0/.system_generated/logs/transcript_full.jsonl');
  const rl = readline.createInterface({
    input: fileStream,
    crlfDelay: Infinity
  });

  let lastUserInput = null;
  for await (const line of rl) {
    if (!line.trim()) continue;
    try {
      const obj = JSON.parse(line);
      if (obj.type === 'USER_INPUT') {
        lastUserInput = obj;
      }
    } catch (e) {}
  }

  if (lastUserInput) {
    fs.writeFileSync('d:/cookmate/scratch/last_user_prompt.txt', lastUserInput.content, 'utf8');
    console.log('Saved last user input, step:', lastUserInput.step_index, 'len:', lastUserInput.content.length);
  } else {
    console.log('No USER_INPUT found');
  }
}

main();
