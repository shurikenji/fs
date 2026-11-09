const { createDynamicAccount, findBank, render } = require("vietqr-node");

async function main() {
  const [bankId, accountNo, accountName, amountRaw, description, templateRaw = "compact"] = process.argv.slice(2);
  const bank = findBank(bankId || "");
  if (!bank) throw new Error(`Unsupported bank identifier: ${bankId || "<empty>"}`);

  const amount = Number(amountRaw);
  const template = templateRaw === "compact2" ? "compact" : templateRaw;
  if (!["compact", "print", "qr_only"].includes(template)) {
    throw new Error(`Unsupported VietQR template: ${templateRaw}`);
  }

  const payload = createDynamicAccount(bank.bin, accountNo, amount, description);
  const png = await render(payload, {
    template,
    format: "png",
    bankBin: bank.bin,
    accountNo,
    accountName,
    amount,
    description,
  });
  process.stdout.write(png);
}

main().catch((error) => {
  process.stderr.write(`${error.code ? `${error.code}: ` : ""}${error.message}\n`);
  process.exitCode = 1;
});
