/*
  Warnings:

  - You are about to drop the column `runId` on the `checkpoints` table. All the data in the column will be lost.
  - Added the required column `threadId` to the `checkpoints` table without a default value. This is not possible if the table is not empty.

*/
-- DropForeignKey
ALTER TABLE "checkpoints" DROP CONSTRAINT "checkpoints_runId_fkey";

-- DropIndex
DROP INDEX "checkpoints_runId_idx";

-- AlterTable
ALTER TABLE "checkpoints" DROP COLUMN "runId",
ADD COLUMN     "threadId" TEXT NOT NULL;

-- CreateIndex
CREATE INDEX "checkpoints_threadId_idx" ON "checkpoints"("threadId");

-- AddForeignKey
ALTER TABLE "checkpoints" ADD CONSTRAINT "checkpoints_threadId_fkey" FOREIGN KEY ("threadId") REFERENCES "research_runs"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
