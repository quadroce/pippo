import { PrismaClient } from "@prisma/client";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const prisma = new PrismaClient();

type SeedCountry = {
  code: string;
  name: string;
  entryUrl: string;
  timezone: string;
  language: string;
};

async function main() {
  const adminEmail = process.env.ADMIN_EMAIL?.trim().toLowerCase();
  if (!adminEmail) throw new Error("ADMIN_EMAIL is required to seed the first admin");

  const countries: SeedCountry[] = JSON.parse(
    readFileSync(join(__dirname, "countries.json"), "utf8"),
  );
  for (const c of countries) {
    // Do not overwrite edits made from the Settings page: only create missing rows.
    await prisma.country.upsert({ where: { code: c.code }, update: {}, create: c });
  }

  await prisma.user.upsert({
    where: { email: adminEmail },
    update: { role: "admin" },
    create: { email: adminEmail, role: "admin" },
  });

  await prisma.setting.upsert({
    where: { key: "activeCountry" },
    update: {},
    create: { key: "activeCountry", value: "IT" },
  });

  console.log(`Seeded ${countries.length} countries, admin ${adminEmail}, active country IT`);
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
