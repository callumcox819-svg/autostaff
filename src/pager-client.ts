import { randomUUID } from "node:crypto";
import { cleanPagerCookies, enrichPagerCookies, extractPagerBearerToken, parseCookieHeader } from "./clerk-auth.js";
import {
  parsePagerMovedEndpoint,
  resolvePagerApiBaseUrl,
  resolvePagerWebBaseUrl,
} from "./pager-urls.js";
import { looksLikeLeakedChannelFolder } from "./status-folders.js";

export type PagerChannel = {
  id: string;
  name: string;
  channelSource?: string | null;
  organizationId?: string | null;
};

export type PagerSessionSummary = {
  organizationId?: string;
  organizationName?: string;
  organizationSlug?: string;
  channelCount: number;
  channels: PagerChannel[];
  templateBanks: PagerTemplateBank[];
};

export type PagerTemplateBank = {
  id: string;
  name: string;
  replyCount: number;
};

export type PagerConversation = {
  id: string;
  channelId?: string;
  statusId?: string | null;
  lastMessageDirection?: string;
  lastMessageAt?: string;
  conversationState?: string;
  unreadCount?: number;
  isUnread?: boolean;
  clientPSID?: string;
  responsibleUserId?: string;
  responsibleuserId?: string;
  channel?: { id?: string; name?: string };
  status?: { id?: string; name?: string };
  client?: { psid?: string; PSID?: string };
};

export type PagerStatus = {
  id: string;
  name: string;
};

export type PagerMessage = {
  id: string;
  text?: string;
  messageDirection?: string;
  authorId?: string;
  createdAt?: string;
  isDelivered?: boolean;
  facebookMessageId?: string;
  reaction?: string | null;
  attachments?: Array<{
    type?: string;
    sticker_id?: string;
    width?: number;
    height?: number;
    payload?: {
      url?: string;
      sticker_id?: string;
      width?: number;
      height?: number;
    };
  }>;
};

export type PagerSavedReply = {
  id: string;
  text: string;
  name?: string;
};

export class PagerApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: string,
  ) {
    super(`Pager API ${status}: ${body.slice(0, 200)}`);
  }
}

export class PagerSessionError extends Error {
  constructor(message: string) {
    super(message);
  }
}

export function isPagerSessionError(error: unknown): boolean {
  return error instanceof PagerSessionError;
}

const BROWSER_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

export class PagerClient {
  private orgId = "";
  private orgSlug = "";
  private sessionUserId = "";
  private cachedOperatorImageUrl = "";
  private cookieHeader: string;
  private apiBaseUrl: string;
  private readonly webBaseUrl: string;

  constructor(
    private readonly options: {
      baseUrl: string;
      webBaseUrl?: string;
      cookieHeader: string;
      orgId?: string;
      orgSlug?: string;
      locale?: string;
      sessionUserId?: string;
    },
  ) {
    this.apiBaseUrl = resolvePagerApiBaseUrl(options.baseUrl);
    this.webBaseUrl = resolvePagerWebBaseUrl(options.baseUrl, options.webBaseUrl);
    this.orgId = options.orgId ?? "";
    this.orgSlug = options.orgSlug ?? "";
    this.cookieHeader = cleanPagerCookies(options.cookieHeader);
    const cookieUser = parseCookieHeader(this.cookieHeader)._pager_user_id?.trim();
    if (options.sessionUserId?.startsWith("user_")) {
      this.sessionUserId = options.sessionUserId;
    } else if (cookieUser?.startsWith("user_")) {
      this.sessionUserId = cookieUser;
    }
    this.injectSessionCookies(this.orgId, undefined, this.sessionUserId || undefined);
  }

  getCookieHeader(): string {
    return this.cookieHeader;
  }

  getOrganizationId(): string {
    return this.orgId;
  }

  getOrganizationSlug(): string {
    return this.orgSlug;
  }

  async verifyApiSession(): Promise<PagerChannel[]> {
    const channels = await this.request<PagerChannel[]>("/api/channel", {
      method: "GET",
      referer: this.chatReferer(),
    });
    if (!Array.isArray(channels)) {
      throw new PagerSessionError("Pager /api/channel returned non-array payload");
    }
    return channels;
  }

  async syncOrgIdFromChannels(): Promise<string> {
    try {
      const channels = await this.verifyApiSession();
      const orgId = channels.find((channel) => channel.organizationId)?.organizationId ?? "";
      if (orgId.startsWith("org_")) {
        this.orgId = orgId;
        this.injectSessionCookies(orgId, this.orgSlug);
        return orgId;
      }
    } catch (error) {
      if (isPagerSessionError(error)) {
        throw error;
      }
      console.warn("syncOrgIdFromChannels failed:", formatError(error));
    }
    return this.orgId;
  }

  injectSessionCookies(orgId?: string, orgSlug?: string, pagerUserId?: string): void {
    this.cookieHeader = enrichPagerCookies(this.cookieHeader, {
      organizationId: orgId || this.orgId,
      pagerUserId,
    });
    if (orgId?.startsWith("org_")) {
      this.orgId = orgId;
    }
    if (orgSlug) {
      this.orgSlug = orgSlug;
    }
  }

  async prepareSession(): Promise<void> {
    await this.warmSession();

    const cookieOrg = this.parseCookies()._pager_org_id?.trim();
    if (!this.orgId?.startsWith("org_") && cookieOrg?.startsWith("org_")) {
      this.orgId = cookieOrg;
    }

    if (!this.orgSlug) {
      await this.discoverOrgSlug();
    }

    if (!this.orgId?.startsWith("org_")) {
      await this.syncOrgIdFromChannels();
    }

    if (!this.orgId?.startsWith("org_")) {
      await this.resolveOrgIdLive();
    } else {
      this.injectSessionCookies(this.orgId, this.orgSlug);
    }
  }

  async bootstrapSession(): Promise<{
    organizationId: string;
    organizationSlug: string;
    organizationName?: string;
    cookieHeader: string;
  }> {
    await this.prepareSession();
    await this.syncOrgIdFromChannels();
    const organizationId = await this.ensureOrgId();
    const organization = await this.getOrganization().catch(() => undefined);
    const organizationSlug = this.orgSlug || organization?.slug || "";
    this.injectSessionCookies(organizationId, organizationSlug);

    return {
      organizationId,
      organizationSlug,
      organizationName: organization?.name,
      cookieHeader: this.cookieHeader,
    };
  }

  async listStatusesApi(): Promise<PagerStatus[]> {
    const orgId = await this.ensureOrgId();
    try {
      const payload = await this.requestWithOrgRetry<unknown>("/api/status", {
        method: "GET",
        params: { orgId },
        referer: this.chatReferer(),
      });
      return parseStatusItems(extractPayloadArray(payload));
    } catch (error) {
      console.warn(`GET /api/status orgId=${orgId.slice(0, 12)}:`, formatError(error));
      return [];
    }
  }

  async resolveOrgIdLive(): Promise<string> {
    const cookieOrg = this.parseCookies()._pager_org_id?.trim();
    if (cookieOrg?.startsWith("org_")) {
      this.orgId = cookieOrg;
      this.injectSessionCookies(cookieOrg, this.orgSlug);
      return cookieOrg;
    }

    if (this.orgId?.startsWith("org_")) {
      this.injectSessionCookies(this.orgId, this.orgSlug);
      return this.orgId;
    }

    const savedOrg = this.orgId;
    const savedSlug = this.orgSlug;
    this.orgId = "";

    await this.warmSession();
    if (this.orgId?.startsWith("org_")) {
      this.injectSessionCookies(this.orgId, this.orgSlug);
      return this.orgId;
    }

    const fromChannels = await this.syncOrgIdFromChannels();
    if (fromChannels.startsWith("org_")) {
      return fromChannels;
    }

    for (const getter of [
      () => this.tryOrgFromConversations(),
      () => this.tryOrgBySlug(),
    ]) {
      const orgId = await getter();
      if (orgId) {
        this.injectSessionCookies(orgId, this.orgSlug);
        return orgId;
      }
    }

    const html = await this.fetchChatsHtml();
    if (html) {
      const orgFromHtml = extractOrgFromHtml(html);
      if (orgFromHtml) {
        this.orgId = orgFromHtml;
        if (!this.orgSlug) {
          const slug = extractOrgSlugFromHtml(html);
          if (slug) {
            this.orgSlug = slug;
          }
        }
        this.injectSessionCookies(this.orgId, this.orgSlug);
        return orgFromHtml;
      }
    }

    this.orgId = savedOrg;
    this.orgSlug = savedSlug;
    if (this.orgId?.startsWith("org_")) {
      return this.orgId;
    }
    return this.discoverOrgId();
  }

  async getChannels(): Promise<PagerChannel[]> {
    const orgId = await this.ensureOrgId();
    const params = orgId ? { orgId } : undefined;
    const payload = await this.request<PagerChannel[]>("/api/channel", { method: "GET", params });
    return Array.isArray(payload) ? payload : [];
  }

  async getOrganization(): Promise<{ id?: string; name?: string; slug?: string } | undefined> {
    try {
      const payload = await this.request<{ id?: string; name?: string; slug?: string }>(
        "/api/organization",
        { method: "GET" },
      );
      if (payload?.id) {
        this.orgId = payload.id;
      }
      if (payload?.slug) {
        this.orgSlug = payload.slug;
      }
      return payload;
    } catch {
      return undefined;
    }
  }

  async getTemplateBanks(): Promise<PagerTemplateBank[]> {
    const orgId = await this.ensureOrgId();
    if (!orgId) {
      return [];
    }

    const foldersPayload = await this.request<unknown>("/api/reply/folder", {
      method: "GET",
      params: { orgId },
    });
    const folders = normalizeReplyFolders(foldersPayload);
    if (!folders.length) {
      return [];
    }

    const withCounts = await Promise.all(
      folders.map(async (folder) => {
        try {
          const replies = await this.getSavedReplies(folder.id);
          return {
            ...folder,
            replyCount: replies.length,
          };
        } catch {
          return folder;
        }
      }),
    );

    return withCounts.sort((left, right) => left.name.localeCompare(right.name));
  }

  async listStatuses(): Promise<PagerStatus[]> {
    return this.loadAllStatuses();
  }

  async loadAllStatuses(): Promise<PagerStatus[]> {
    await this.prepareSession();
    const orgId = await this.ensureOrgId();
    const channelFilter = await this.loadChannelFilter();
    const merged = new Map<string, string>();

    const addStatuses = (items: PagerStatus[]) => {
      for (const item of filterStatusesExcludingChannels(items, channelFilter)) {
        merged.set(item.id, item.name);
      }
    };

    addStatuses(await this.listStatusesApi());

    if (merged.size < 1) {
      try {
        const orgPayload = await this.requestWithOrgRetry<unknown>("/api/organization", {
          method: "GET",
          params: { orgId },
          referer: this.chatReferer(),
        });
        const fromOrg = new Map<string, string>();
        collectStatusesFromPayload(orgPayload, fromOrg);
        addStatuses([...fromOrg.entries()].map(([id, name]) => ({ id, name })));
      } catch (error) {
        console.warn("Pager organization status parse failed:", formatError(error));
      }
    }

    if (merged.size < 1) {
      try {
        addStatuses(await this.discoverStatusesFromConversations());
      } catch (error) {
        console.warn("Pager status discovery via conversations failed:", formatError(error));
      }
    }

    if (merged.size < 1) {
      const html = await this.fetchChatsHtml();
      if (html) {
        if (!this.orgSlug) {
          const slug = extractOrgSlugFromHtml(html);
          if (slug) {
            this.orgSlug = slug;
          }
        }
        if (!this.orgId) {
          const orgFromHtml = extractOrgFromHtml(html);
          if (orgFromHtml) {
            this.orgId = orgFromHtml;
            this.injectSessionCookies(orgFromHtml, this.orgSlug);
          }
        }
        addStatuses(discoverStatusesFromHtml(html, channelFilter));
      }
    }

    const statuses = [...merged.entries()]
      .map(([id, name]) => ({ id, name }))
      .sort((left, right) => left.name.localeCompare(right.name));

    console.log(
      `Pager statuses loaded: ${statuses.length} (orgId=${orgId.slice(0, 12)}… slug=${this.orgSlug || "?"})`,
    );
    return statuses;
  }

  private async loadChannelFilter(): Promise<ChannelFilter> {
    try {
      const channels = await this.getChannels();
      return buildChannelFilter(channels);
    } catch {
      return { ids: new Set(), names: new Set() };
    }
  }

  private async discoverOrgSlug(): Promise<string> {
    if (this.orgSlug) {
      return this.orgSlug;
    }

    if (this.options.orgSlug) {
      this.orgSlug = this.options.orgSlug;
      return this.orgSlug;
    }

    const organization = await this.getOrganization();
    const slug = firstString(organization?.slug, organization?.name?.toLowerCase());
    if (slug) {
      this.orgSlug = slug;
      return slug;
    }

    const html = await this.fetchChatsHtml();
    const fromHtml = extractOrgSlugFromHtml(html);
    if (fromHtml) {
      this.orgSlug = fromHtml;
    }
    return this.orgSlug;
  }

  private async discoverStatusesFromConversations(maxPages = 15): Promise<PagerStatus[]> {
    const seen = new Map<string, string>();

    for (let page = 1; page <= maxPages; page += 1) {
      const batch = await this.listConversations({ page, pageSize: 100 });
      if (!batch.length) {
        break;
      }

      for (const conv of batch) {
        const statusId = (conv.statusId || conv.status?.id || "").trim();
        const statusName = (conv.status?.name || "").trim();
        if (statusId && statusName) {
          seen.set(statusId, statusName);
        }
      }

      if (batch.length < 100) {
        break;
      }
    }

    return [...seen.entries()].map(([id, name]) => ({ id, name }));
  }

  async getSavedReplies(folderId: string): Promise<PagerSavedReply[]> {
    const orgId = await this.ensureOrgId().catch(() => "");
    const payload = await this.request<unknown>("/api/reply", {
      method: "GET",
      params: orgId ? { folderId, orgId } : { folderId },
    });

    const replies: PagerSavedReply[] = [];
    for (const [index, item] of extractPayloadArray(payload).entries()) {
      if (!item || typeof item !== "object") {
        continue;
      }
      const record = item as Record<string, unknown>;
      const text = firstString(
        record.text,
        record.body,
        record.message,
        record.content,
        record.replyText,
      );
      if (!text) {
        continue;
      }
      const id =
        firstString(record.id, record._id, record.replyId) ?? `${folderId}:${index}`;
      replies.push({
        id,
        text,
        name: firstString(record.name, record.title, record.label),
      });
    }
    return replies;
  }

  async listConversations(options?: {
    page?: number;
    pageSize?: number;
    channelId?: string;
    statusId?: string;
  }): Promise<PagerConversation[]> {
    const orgId = await this.ensureOrgId();
    const params: Record<string, string> = {
      orgId,
      page: String(options?.page ?? 1),
      pageSize: String(options?.pageSize ?? 50),
    };
    if (options?.channelId) {
      params.channelId = options.channelId;
    }
    if (options?.statusId !== undefined) {
      params.statusId = options.statusId;
    }

    const payload = await this.requestWithOrgRetry<PagerConversation[]>(
      "/api/conversation",
      { method: "GET", params, referer: this.chatReferer() },
    );
    const conversations = Array.isArray(payload)
      ? payload.map((item) => normalizePagerConversation(item))
      : [];
    if (options?.channelId) {
      return conversations.filter((conv) => conv.channelId === options.channelId);
    }
    return conversations;
  }

  async collectConversationsForChannels(
    channelIds: string[],
    maxPages = 5,
  ): Promise<PagerConversation[]> {
    await this.prepareSession();
    await this.syncOrgIdFromChannels();

    try {
      return await this.collectConversationsForChannelsInner(channelIds, maxPages);
    } catch (error) {
      if (isPagerSessionError(error)) {
        throw error;
      }
      if (!isOrgIdError(error)) {
        throw error;
      }
      console.warn("collectConversations org retry:", formatError(error));
      this.orgId = "";
      await this.resolveOrgIdLive();
      await this.syncOrgIdFromChannels();
      return this.collectConversationsForChannelsInner(channelIds, maxPages);
    }
  }

  private async collectConversationsForChannelsInner(
    channelIds: string[],
    maxPages: number,
  ): Promise<PagerConversation[]> {
    const enabled = new Set(channelIds);
    const seen = new Map<string, PagerConversation>();

    const addBatch = (conversations: PagerConversation[]) => {
      for (const conv of conversations) {
        const channelId = conv.channelId || conv.channel?.id;
        if (!channelId || !enabled.has(channelId)) {
          continue;
        }
        seen.set(conv.id, conv);
      }
    };

    for (const channelId of channelIds) {
      const head = await this.listConversations({ channelId, page: 1, pageSize: 200 });
      addBatch(head);
      for (let page = 2; page <= maxPages; page += 1) {
        const batch = await this.listConversations({ channelId, page, pageSize: 100 });
        if (!batch.length) {
          break;
        }
        addBatch(batch);
        if (batch.length < 100) {
          break;
        }
      }
    }

    for (let page = 1; page <= 12; page += 1) {
      const batch = await this.listConversations({ page, pageSize: 100 });
      if (!batch.length) {
        break;
      }
      addBatch(batch);
      if (batch.length < 100) {
        break;
      }
    }

    return [...seen.values()];
  }

  async openConversation(convId: string): Promise<PagerConversation | undefined> {
    const orgId = await this.ensureOrgId();
    try {
      const payload = await this.request<PagerConversation>(`/api/conversation/${convId}`, {
        method: "GET",
        params: { orgId },
        referer: this.chatReferer(convId),
      });
      return payload ? normalizePagerConversation(payload) : undefined;
    } catch {
      return undefined;
    }
  }

  async listMessages(convId: string, page = 1, pageSize = 50): Promise<PagerMessage[]> {
    const orgId = await this.ensureOrgId();
    const payload = await this.request<unknown>("/api/message", {
      method: "GET",
      params: {
        orgId,
        convId,
        page: String(page),
        pageSize: String(pageSize),
      },
    });
    return Array.isArray(payload) ? payload.map((item) => normalizePagerMessage(item)) : [];
  }

  async resolveSessionUserId(): Promise<string> {
    return this.resolveOperatorUserId();
  }

  async probeOperatorUserId(): Promise<string> {
    const resolved = await this.resolveOperatorUserId();
    if (resolved) {
      this.sessionUserId = resolved;
      this.injectSessionCookies(this.orgId, this.orgSlug, resolved);
    }
    return resolved;
  }

  async resolveOperatorUserId(authorId = ""): Promise<string> {
    if (this.sessionUserId?.startsWith("user_") && !authorId) {
      const validated = await this.mapToMessageAuthorId(this.sessionUserId);
      if (validated) {
        return validated;
      }
    }

    const hints = [
      authorId,
      this.sessionUserId,
      this.parseCookies()._pager_user_id,
      await this.resolveSessionUserIdFromApi(),
      await this.resolveSessionUserIdFromClerk(),
    ];

    for (const hint of hints) {
      const normalized = (hint || "").trim();
      if (!normalized.startsWith("user_")) {
        continue;
      }
      const mapped = await this.mapToMessageAuthorId(normalized);
      if (mapped) {
        this.sessionUserId = mapped;
        this.injectSessionCookies(this.orgId, this.orgSlug, mapped);
        return mapped;
      }
    }

    const members = await this.fetchOrganizationMembers();
    if (members.length === 1) {
      this.sessionUserId = members[0]!.messageAuthorId;
      this.injectSessionCookies(this.orgId, this.orgSlug, members[0]!.messageAuthorId);
      return members[0]!.messageAuthorId;
    }

    return "";
  }

  private async resolveSessionUserIdFromApi(): Promise<string> {
    const orgId = await this.ensureOrgId();
    for (const path of ["/api/user/me", "/api/users/me", "/api/user"]) {
      try {
        const payload = await this.request<unknown>(path, {
          method: "GET",
          params: { orgId },
        });
        const userId = extractUserId(payload);
        if (userId) {
          return userId;
        }
      } catch {
        continue;
      }
    }
    return "";
  }

  private async resolveSessionUserIdFromClerk(): Promise<string> {
    try {
      const response = await fetch(
        "https://clerk.pager.co.ua/v1/client?__clerk_api_version=2024-10-01&_clerk_js_version=5.68.0",
        {
          headers: {
            Accept: "*/*",
            Cookie: cleanPagerCookies(this.cookieHeader),
            "User-Agent": BROWSER_UA,
            Origin: this.webBaseUrl,
            Referer: `${this.webBaseUrl}/`,
          },
        },
      );
      if (!response.ok) {
        return "";
      }
      const payload = (await response.json()) as {
        response?: {
          sessions?: Array<{ user?: { id?: string } }>;
        };
      };
      const userId = payload.response?.sessions?.[0]?.user?.id?.trim();
      return userId?.startsWith("user_") ? userId : "";
    } catch {
      return "";
    }
  }

  private async mapToMessageAuthorId(hint: string): Promise<string> {
    const normalized = hint.trim();
    if (!normalized.startsWith("user_")) {
      return "";
    }

    const members = await this.fetchOrganizationMembers();
    for (const member of members) {
      if (member.messageAuthorId === normalized) {
        return member.messageAuthorId;
      }
      if (member.candidateIds.includes(normalized)) {
        return member.messageAuthorId;
      }
    }
    return "";
  }

  private async fetchOrganizationMembers(): Promise<
    Array<{ messageAuthorId: string; candidateIds: string[]; imageUrl: string }>
  > {
    const orgId = await this.ensureOrgId();
    try {
      const payload = await this.request<unknown>("/api/organizationMember", {
        method: "GET",
        params: { orgId },
      });
      if (!Array.isArray(payload)) {
        return [];
      }

      const members: Array<{ messageAuthorId: string; candidateIds: string[]; imageUrl: string }> =
        [];
      for (const item of payload) {
        if (!item || typeof item !== "object") {
          continue;
        }
        const record = item as Record<string, unknown>;
        const user =
          record.user && typeof record.user === "object"
            ? (record.user as Record<string, unknown>)
            : {};
        const messageAuthorId = firstString(record.userId, record.pagerUserId, user.id, record.id);
        if (!messageAuthorId?.startsWith("user_")) {
          continue;
        }
        const candidateIds = [
          messageAuthorId,
          firstString(record.pagerUserId, user.id, record.id),
        ].filter((value): value is string => Boolean(value?.startsWith("user_")));
        members.push({
          messageAuthorId,
          candidateIds: [...new Set(candidateIds)],
          imageUrl: firstString(record.imageUrl, user.imageUrl) ?? "",
        });
      }
      return members;
    } catch {
      return [];
    }
  }

  async takeConversation(convId: string, userId: string): Promise<boolean> {
    const uid = userId.trim();
    if (!uid) {
      return false;
    }

    if ((await this.getResponsibleUserId(convId)) === uid) {
      return true;
    }

    const orgId = await this.ensureOrgId();
    const referer = this.chatReferer(convId);
    const attempts: Array<{ params: Record<string, string>; body: Record<string, unknown> }> = [
      { params: { userId: uid, orgId }, body: { responsibleUserId: uid } },
      {
        params: { userId: uid, orgId },
        body: { responsibleuserId: uid },
      },
      { params: { userId: uid }, body: { responsibleUserId: uid } },
    ];

    for (const attempt of attempts) {
      try {
        await this.request(`/api/conversation/${convId}`, {
          method: "PATCH",
          params: attempt.params,
          body: attempt.body,
          referer,
        });
      } catch {
        continue;
      }
      if (await this.waitTakeConfirmed(convId, uid)) {
        return true;
      }
    }

    return (await this.getResponsibleUserId(convId)) === uid;
  }

  /** Take + mark read so handled threads clear unread badges in Pager UI. */
  async acknowledgeConversation(convId: string): Promise<void> {
    const userId = await this.probeOperatorUserId();
    if (!userId) {
      return;
    }
    try {
      await this.takeConversation(convId, userId);
    } catch {
      // non-fatal
    }
    try {
      await this.markConversationRead(convId, userId);
    } catch {
      // non-fatal
    }
  }

  async prepareOutbound(
    convId: string,
    conv?: PagerConversation,
    authorId = "",
  ): Promise<{ userId: string; conv: PagerConversation }> {
    await this.warmSession();
    const userId = (await this.resolveOperatorUserId(authorId)).trim();
    if (!userId) {
      throw new PagerApiError(
        400,
        JSON.stringify({ error: "operator user id missing — re-login to Pager" }),
      );
    }

    let convData: PagerConversation = { ...(conv ?? { id: convId }) };
    const fresh = await this.openConversation(convId);
    if (fresh) {
      convData = { ...convData, ...fresh };
    }

    let taken = await this.takeConversation(convId, userId);
    if (!taken) {
      await sleep(800);
      const retryConv = await this.openConversation(convId);
      if (retryConv) {
        convData = { ...convData, ...retryConv };
      }
      taken = await this.takeConversation(convId, userId);
    }
    if (!taken) {
      throw new PagerApiError(
        502,
        JSON.stringify({
          error: "take chat failed — operator not assigned",
          conv: convId.slice(0, 8),
        }),
      );
    }

    // Do NOT mark read before a successful send — failed sends were clearing badges while
    // leaving customers without a reply (CM «Без статусу» looked «taken» but silent).
    const afterTake = await this.openConversation(convId);
    if (afterTake) {
      convData = { ...convData, ...afterTake };
    }

    await this.fetchConversationChatPage(convId);
    try {
      await this.listMessages(convId, 1, 1);
    } catch {
      // non-fatal
    }

    return { userId, conv: convData };
  }

  async sendMessageReliable(
    convId: string,
    text: string,
    options?: {
      userId?: string;
      channelId?: string;
      conv?: PagerConversation;
      attachments?: Array<{ type: string; payload: { url: string } }>;
    },
  ): Promise<boolean> {
    const prepared = await this.prepareOutbound(convId, options?.conv, options?.userId);
    const userId = prepared.userId;
    let conv = prepared.conv;
    let channelId = (options?.channelId || conv.channelId || conv.channel?.id || "").trim();

    if (!channelId) {
      const opened = await this.openConversation(convId);
      if (opened) {
        conv = { ...conv, ...opened };
        channelId = (opened.channelId || opened.channel?.id || "").trim();
      }
    }

    if (!channelId) {
      throw new PagerApiError(
        400,
        JSON.stringify({ error: "channelId missing", conv: convId.slice(0, 8) }),
      );
    }

    const attempts: Array<() => Promise<Record<string, unknown>>> = [
      () =>
        this.sendMessageSpa(convId, text, {
          userId,
          channelId,
          conv,
          attachments: options?.attachments,
        }),
      () => this.postMessageMinimal(convId, text, userId, channelId),
    ];

    let lastError: unknown;
    let hardApiFailure = false;
    const markReadAfterSuccess = async () => {
      try {
        await this.markConversationRead(convId, userId);
      } catch {
        // non-fatal
      }
    };

    for (const attempt of attempts) {
      try {
        const result = await attempt();
        if (messageDelivered(result)) {
          await markReadAfterSuccess();
          return true;
        }
      } catch (error) {
        lastError = error;
        const errText = formatError(error).toLowerCase();
        if (errText.includes("imageurl") || errText.includes(" 500") || errText.includes("operator user")) {
          hardApiFailure = true;
        }
        console.warn(`Pager send attempt failed for ${convId.slice(0, 8)}:`, formatError(error));
      }
    }

    // imageUrl / operator identity 500s usually mean stale session user — refresh once.
    const errorText = formatError(lastError).toLowerCase();
    if (errorText.includes("imageurl") || errorText.includes("operator user")) {
      this.sessionUserId = "";
      this.cachedOperatorImageUrl = "";
      try {
        const retriedUser = (await this.resolveOperatorUserId()).trim();
        if (retriedUser) {
          const freshConv = (await this.openConversation(convId)) ?? conv;
          const result = await this.sendMessageSpa(convId, text, {
            userId: retriedUser,
            channelId,
            conv: freshConv,
            attachments: options?.attachments,
          });
          if (messageDelivered(result)) {
            await markReadAfterSuccess();
            return true;
          }
        }
      } catch (error) {
        hardApiFailure = true;
        console.warn(`Pager send identity retry failed for ${convId.slice(0, 8)}:`, formatError(error));
      }
    }

    // Never burn 45s per failed send — that starves CM «Без статусу» for minutes.
    const delivered = await this.waitMessageDelivered(
      convId,
      text,
      userId,
      hardApiFailure ? 2_000 : 8_000,
    );
    if (delivered) {
      await markReadAfterSuccess();
    }
    return delivered;
  }

  async sendImageReliable(
    convId: string,
    image: { buffer: Buffer; mimeType: string; filename: string },
    options?: {
      userId?: string;
      channelId?: string;
      conv?: PagerConversation;
    },
  ): Promise<boolean> {
    const prepared = await this.prepareOutbound(convId, options?.conv, options?.userId);
    const userId = prepared.userId;
    let conv = prepared.conv;
    let channelId = (options?.channelId || conv.channelId || conv.channel?.id || "").trim();

    if (!channelId) {
      const opened = await this.openConversation(convId);
      if (opened) {
        conv = { ...conv, ...opened };
        channelId = (opened.channelId || opened.channel?.id || "").trim();
      }
    }

    if (!channelId) {
      console.warn(`Pager image send skipped ${convId.slice(0, 8)} — channelId missing`);
      return false;
    }

    const uploadedUrl = await this.uploadOutboundImage(convId, image, {
      userId,
      channelId,
      conv,
    });
    if (!uploadedUrl) {
      return false;
    }

    if (uploadedUrl === "__sent__") {
      return true;
    }

    return this.sendMessageReliable(convId, "", {
      userId,
      channelId,
      conv,
      attachments: [{ type: "image", payload: { url: uploadedUrl } }],
    });
  }

  private async uploadOutboundImage(
    convId: string,
    image: { buffer: Buffer; mimeType: string; filename: string },
    options: { userId: string; channelId: string; conv: PagerConversation },
  ): Promise<string | undefined> {
    const orgId = await this.ensureOrgId();
    const referer = this.chatReferer(convId);
    const blob = new Blob([Uint8Array.from(image.buffer)], { type: image.mimeType });
    const uploadAttempts: Array<{ path: string; fields: Record<string, string | Blob> }> = [
      { path: "/api/upload", fields: { file: blob, filename: image.filename } },
      { path: "/api/file", fields: { file: blob, name: image.filename } },
      {
        path: "/api/message/upload",
        fields: {
          file: blob,
          conversationId: convId,
          channelId: options.channelId,
        },
      },
      {
        path: "/api/message",
        fields: {
          file: blob,
          conversationId: convId,
          channelId: options.channelId,
          text: "",
        },
      },
    ];

    for (const attempt of uploadAttempts) {
      try {
        const payload = await this.postMultipart(attempt.path, {
          orgId,
          userId: options.userId,
        }, attempt.fields, referer);
        const url = extractUploadedUrl(payload);
        if (url) {
          console.log(
            `Pager image uploaded conv=${convId.slice(0, 8)} via ${attempt.path} url=${url.slice(0, 48)}`,
          );
          return url;
        }
        if (payload && typeof payload === "object" && messageDelivered(payload as Record<string, unknown>)) {
          console.log(`Pager image sent directly via ${attempt.path} conv=${convId.slice(0, 8)}`);
          return "__sent__";
        }
      } catch (error) {
        console.warn(`Pager image upload miss ${attempt.path}:`, formatError(error));
      }
    }

    return undefined;
  }

  private async postMultipart(
    path: string,
    params: Record<string, string>,
    fields: Record<string, string | Blob>,
    referer?: string,
  ): Promise<unknown> {
    const url = new URL(path, this.apiBaseUrl);
    for (const [key, value] of Object.entries(params)) {
      if (value) {
        url.searchParams.set(key, value);
      }
    }

    const form = new FormData();
    for (const [key, value] of Object.entries(fields)) {
      if (value instanceof Blob) {
        const filename =
          key === "file" && typeof fields.filename === "string" ? fields.filename : "upload.png";
        form.append(key, value, filename);
      } else {
        form.append(key, value);
      }
    }

    const headers = this.buildHeaders({ includeJsonContentType: false });
    if (referer) {
      headers.Referer = referer;
    }

    const response = await fetch(url, {
      method: "POST",
      headers,
      body: form,
    });
    const text = await response.text();
    if (!response.ok) {
      if (response.status === 410) {
        const migrated = parsePagerMovedEndpoint(text);
        if (migrated && migrated !== this.apiBaseUrl) {
          console.warn(`Pager API migrated (upload): ${this.apiBaseUrl} -> ${migrated}`);
          this.apiBaseUrl = migrated;
          return this.postMultipart(path, params, fields, referer);
        }
      }
      throw new PagerApiError(response.status, text);
    }
    if (!text.trim()) {
      return {};
    }
    try {
      return JSON.parse(text) as unknown;
    } catch {
      return { raw: text };
    }
  }

  async downloadAttachment(url: string): Promise<Buffer> {
    const response = await fetch(url, {
      headers: {
        Cookie: cleanPagerCookies(this.cookieHeader),
        "User-Agent": BROWSER_UA,
        Referer: this.webBaseUrl,
      },
    });
    if (!response.ok) {
      throw new Error(`Failed to download attachment: ${response.status}`);
    }
    return Buffer.from(await response.arrayBuffer());
  }

  async validateSession(): Promise<PagerSessionSummary> {
    await this.warmSession();
    const organization = await this.getOrganization();
    const channels = await this.getChannels();
    const templateBanks = await this.getTemplateBanks().catch(() => []);

    if (!channels.length) {
      throw new Error("Pager session is not authorized or returned no channels.");
    }

    if (!this.orgId) {
      const fromChannel = channels.find((channel) => channel.organizationId)?.organizationId;
      if (fromChannel) {
        this.orgId = fromChannel;
      }
    }

    return {
      organizationId: organization?.id ?? this.orgId,
      organizationName: organization?.name,
      organizationSlug: organization?.slug ?? this.orgSlug,
      channelCount: channels.length,
      channels,
      templateBanks,
    };
  }

  private async sendMessageSpa(
    convId: string,
    text: string,
    options: {
      userId: string;
      channelId: string;
      conv: PagerConversation;
      attachments?: Array<{ type: string; payload: { url: string } }>;
    },
  ): Promise<Record<string, unknown>> {
    const orgId = await this.ensureOrgId();
    const referer = this.chatReferer(convId);
    let convData = options.conv;
    if (!convData.channelId) {
      const opened = await this.openConversation(convId);
      if (opened) {
        convData = opened;
      }
    }

    const channelId = (options.channelId || convData.channelId || convData.channel?.id || "").trim();
    if (!channelId) {
      throw new PagerApiError(400, JSON.stringify({ error: "channelId missing", conv: convId.slice(0, 8) }));
    }

    const recipient = extractRecipientPsid(convData);
    const imageUrl = await this.getOperatorImageUrl(options.userId, convData);
    const now = new Date().toISOString();
    const payload: Record<string, unknown> = {
      id: randomUUID(),
      channelId,
      text,
      conversationId: convId,
      messageDirection: "outgoing",
      authorId: options.userId,
      author: { id: options.userId, imageUrl: imageUrl || "" },
      recipient: recipient || "",
      createdAt: now,
      updatedAt: now,
      lastMessageAt: now,
      optimistic: true,
      isDelivered: null,
      replyToMessageId: null,
    };
    if (options.attachments?.length) {
      payload.attachments = options.attachments;
    }

    const params: Record<string, string> = { orgId };
    if (options.userId) {
      params.userId = options.userId;
    }

    const result = await this.request<Record<string, unknown>>("/api/message", {
      method: "POST",
      params,
      body: payload,
      referer,
    });
    if (!result || typeof result !== "object") {
      throw new PagerApiError(502, '{"error":"empty message response"}');
    }
    return result;
  }

  private async postMessageMinimal(
    convId: string,
    text: string,
    userId: string,
    channelId: string,
  ): Promise<Record<string, unknown>> {
    const orgId = await this.ensureOrgId();
    const imageUrl = await this.getOperatorImageUrl(userId);
    const params: Record<string, string> = { orgId };
    if (userId) {
      params.userId = userId;
    }

    const result = await this.request<Record<string, unknown>>("/api/message", {
      method: "POST",
      params,
      body: {
        conversationId: convId,
        channelId,
        text,
        authorId: userId,
        author: { id: userId, imageUrl: imageUrl || "" },
        messageDirection: "outgoing",
      },
      referer: this.chatReferer(convId),
    });
    if (!result || typeof result !== "object") {
      throw new PagerApiError(502, '{"error":"empty message response"}');
    }
    return result;
  }

  async patchConversationStatus(convId: string, statusId: string, userId: string): Promise<void> {
    const orgId = await this.ensureOrgId();
    await this.request(`/api/conversation/${convId}`, {
      method: "PATCH",
      params: { userId, orgId },
      body: { statusId },
      referer: this.chatReferer(convId),
    });
  }

  private async markConversationRead(convId: string, userId: string): Promise<void> {
    const orgId = await this.ensureOrgId();
    await this.request(`/api/conversation/${convId}`, {
      method: "PATCH",
      params: { userId, orgId },
      body: { conversationState: "read" },
      referer: this.chatReferer(convId),
    });
  }

  private async getResponsibleUserId(convId: string): Promise<string> {
    const conv = await this.openConversation(convId);
    if (!conv) {
      return "";
    }
    const nested = conv as PagerConversation & {
      responsibleUser?: { id?: string };
    };
    return (
      conv.responsibleUserId ||
      conv.responsibleuserId ||
      nested.responsibleUser?.id ||
      ""
    ).trim();
  }

  private async waitTakeConfirmed(convId: string, userId: string, attempts = 10): Promise<boolean> {
    for (let index = 0; index < attempts; index += 1) {
      const responsible = await this.getResponsibleUserId(convId);
      if (responsible === userId) {
        return true;
      }
      const members = await this.fetchOrganizationMembers();
      const member = members.find(
        (item) => item.messageAuthorId === userId || item.candidateIds.includes(userId),
      );
      if (member && responsible === member.messageAuthorId) {
        return true;
      }
      await sleep(500);
    }
    return false;
  }

  private async getOperatorImageUrl(userId: string, conv?: PagerConversation): Promise<string> {
    if (!userId) {
      return this.cachedOperatorImageUrl;
    }

    const nested = conv as (PagerConversation & { responsibleUser?: { imageUrl?: string } }) | undefined;
    const fromConv = nested?.responsibleUser?.imageUrl?.trim();
    if (fromConv) {
      this.cachedOperatorImageUrl = fromConv;
      return fromConv;
    }

    if (this.cachedOperatorImageUrl) {
      return this.cachedOperatorImageUrl;
    }

    const members = await this.fetchOrganizationMembers();
    for (const member of members) {
      if (member.messageAuthorId === userId || member.candidateIds.includes(userId)) {
        const url = (member.imageUrl || "").trim();
        if (url) {
          this.cachedOperatorImageUrl = url;
          return url;
        }
      }
    }
    // Prefer any known org avatar over empty — empty author.imageUrl triggers Pager 500s.
    for (const member of members) {
      const url = (member.imageUrl || "").trim();
      if (url) {
        this.cachedOperatorImageUrl = url;
        return url;
      }
    }
    return "";
  }

  private async waitMessageDelivered(
    convId: string,
    text: string,
    userId: string,
    timeoutMs = 45_000,
  ): Promise<boolean> {
    const needle = text.trim().toLowerCase().slice(0, 72);
    if (!needle) {
      return false;
    }

    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      try {
        const messages = await this.listMessages(convId, 1, 15);
        for (const message of messages) {
          const direction = (message.messageDirection || "").toLowerCase();
          if (direction !== "outgoing" && direction !== "out") {
            continue;
          }
          const author = (message.authorId || "").trim();
          if (userId && author && author !== userId) {
            continue;
          }
          const body = (message.text || "").trim().toLowerCase();
          if (!body.includes(needle.slice(0, 40)) && !needle.includes(body.slice(0, 40))) {
            continue;
          }
          if (message.isDelivered || message.facebookMessageId) {
            return true;
          }
        }
      } catch {
        // keep polling
      }
      await sleep(700);
    }
    return false;
  }

  private async fetchConversationChatPage(convId: string): Promise<void> {
    if (!this.orgSlug || !convId) {
      return;
    }
    const locale = this.options.locale ?? "uk";
    const path = `/${locale}/${this.orgSlug}/chats/${convId}`;
    try {
      await fetch(new URL(path, this.webBaseUrl), {
        method: "GET",
        headers: {
          Accept: "text/html",
          Cookie: cleanPagerCookies(this.cookieHeader),
          Referer: this.chatReferer(),
          "User-Agent": BROWSER_UA,
        },
        redirect: "follow",
      });
    } catch {
      // non-fatal
    }
  }

  async warmSession(): Promise<void> {
    const html = await this.fetchChatsHtml();
    if (!html) {
      return;
    }

    const orgFromHtml = extractOrgFromHtml(html);
    if (orgFromHtml) {
      this.orgId = orgFromHtml;
    }
    if (!this.orgSlug) {
      const slug = extractOrgSlugFromHtml(html);
      if (slug) {
        this.orgSlug = slug;
      }
    }
  }

  private async fetchChatsHtml(): Promise<string> {
    const locale = this.options.locale ?? "uk";
    const paths = [
      this.orgSlug ? `/${locale}/${this.orgSlug}/chats` : "",
      `/${locale}/chats`,
      "/chats",
    ].filter(Boolean);

    for (const path of paths) {
      try {
        const response = await fetch(new URL(path, this.webBaseUrl), {
          method: "GET",
          headers: {
            Cookie: cleanPagerCookies(this.cookieHeader),
            Accept: "text/html",
            Referer: `${this.webBaseUrl}/`,
            "User-Agent": BROWSER_UA,
          },
          redirect: "follow",
        });
        const finalUrl = response.url;
        const match = finalUrl.match(/\/(?:uk|en)\/([^/]+)\/chats/i);
        if (match && !this.orgSlug) {
          const slug = match[1].toLowerCase();
          if (!["chats", "sign-in", "en", "uk", "api"].includes(slug)) {
            this.orgSlug = slug;
          }
        }
        const html = await response.text();
        if (html) {
          return html;
        }
      } catch {
        continue;
      }
    }
    return "";
  }

  private async discoverOrgId(): Promise<string> {
    if (this.orgId) {
      return this.orgId;
    }

    const cookieOrg = this.parseCookies()._pager_org_id?.trim();
    if (cookieOrg?.startsWith("org_")) {
      this.orgId = cookieOrg;
      return cookieOrg;
    }

    await this.warmSession();
    if (this.orgId) {
      return this.orgId;
    }

    const organization = await this.getOrganization();
    if (organization?.id) {
      this.orgId = organization.id;
      return organization.id;
    }

    const fromConversations = await this.tryOrgFromConversations();
    if (fromConversations) {
      return fromConversations;
    }

    const fromSlug = await this.tryOrgBySlug();
    if (fromSlug) {
      return fromSlug;
    }

    try {
      const channels = await this.request<PagerChannel[]>("/api/channel", { method: "GET" });
      const orgId = channels.find((channel) => channel.organizationId)?.organizationId ?? "";
      if (orgId) {
        this.orgId = orgId;
        return orgId;
      }
    } catch {
      // fall through
    }

    const html = await this.fetchChatsHtml();
    if (html) {
      const orgFromHtml = extractOrgFromHtml(html);
      if (orgFromHtml) {
        this.orgId = orgFromHtml;
        return orgFromHtml;
      }
    }

    return "";
  }

  private async tryOrgFromConversations(): Promise<string> {
    try {
      const payload = await this.request<unknown>("/api/conversation", {
        method: "GET",
        params: { pageSize: "1", page: "1" },
      });
      if (!Array.isArray(payload) || !payload.length) {
        return "";
      }
      const first = payload[0] as Record<string, unknown>;
      const orgId = String(first.organizationId || first.orgId || "").trim();
      if (orgId.startsWith("org_")) {
        this.orgId = orgId;
        return orgId;
      }
    } catch {
      return "";
    }
    return "";
  }

  private async tryOrgBySlug(): Promise<string> {
    if (!this.orgSlug) {
      return "";
    }
    for (const path of [`/api/organization/${this.orgSlug}`, `/api/organizations/${this.orgSlug}`]) {
      try {
        const payload = await this.request<unknown>(path, { method: "GET" });
        const orgId = extractOrgFromPayload(payload);
        if (orgId) {
          this.orgId = orgId;
          return orgId;
        }
      } catch {
        continue;
      }
    }
    return "";
  }

  private parseCookies(): Record<string, string> {
    return parseCookieHeader(this.cookieHeader);
  }

  private async requestWithOrgRetry<T>(
    path: string,
    options: {
      method: "GET" | "POST" | "PATCH";
      params?: Record<string, string>;
      body?: unknown;
      referer?: string;
    },
  ): Promise<T> {
    try {
      return await this.request<T>(path, options);
    } catch (error) {
      if (!isOrgIdError(error)) {
        throw error;
      }
      const orgId = await this.resolveOrgIdLive();
      if (!orgId) {
        throw error;
      }
      const params = { ...(options.params ?? {}), orgId };
      return this.request<T>(path, { ...options, params });
    }
  }

  private async ensureOrgId(): Promise<string> {
    const orgId = await this.discoverOrgId();
    if (!orgId) {
      throw new PagerApiError(
        400,
        '{"error":"Organization ID required — could not auto-detect orgId"}',
      );
    }
    return orgId;
  }

  private chatReferer(convId?: string): string {
    const locale = this.options.locale ?? "uk";
    const base = this.orgSlug
      ? `${this.webBaseUrl}/${locale}/${this.orgSlug}/chats`
      : `${this.webBaseUrl}/`;
    return convId ? `${base}/${convId}` : base;
  }

  private buildHeaders(options?: {
    accept?: string;
    includeJsonContentType?: boolean;
  }): Record<string, string> {
    const headers: Record<string, string> = {
      Cookie: cleanPagerCookies(this.cookieHeader),
      Accept: options?.accept ?? "*/*",
      "User-Agent": BROWSER_UA,
      Origin: this.webBaseUrl,
      Referer: this.chatReferer(),
    };
    const bearer = extractPagerBearerToken(this.cookieHeader);
    if (bearer) {
      headers.Authorization = `Bearer ${bearer}`;
    }
    if (options?.includeJsonContentType) {
      headers["Content-Type"] = "application/json";
    }
    return headers;
  }

  private async request<T>(
    path: string,
    options: {
      method: "GET" | "POST" | "PATCH";
      params?: Record<string, string>;
      body?: unknown;
      referer?: string;
    },
    allowEndpointMigration = true,
  ): Promise<T> {
    const url = new URL(path, this.apiBaseUrl);
    if (options.params) {
      for (const [key, value] of Object.entries(options.params)) {
        if (value) {
          url.searchParams.set(key, value);
        }
      }
    }

    const headers = this.buildHeaders({
      includeJsonContentType: options.body !== undefined,
    });
    if (options.referer) {
      headers.Referer = options.referer;
    }

    const response = await fetch(url, {
      method: options.method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });

    const text = await response.text();
    if (!response.ok) {
      if (response.status === 410 && allowEndpointMigration) {
        const migrated = parsePagerMovedEndpoint(text);
        if (migrated && migrated !== this.apiBaseUrl) {
          console.warn(`Pager API migrated: ${this.apiBaseUrl} -> ${migrated}`);
          this.apiBaseUrl = migrated;
          return this.request(path, options, false);
        }
      }
      throw new PagerApiError(response.status, text);
    }

    if (!text.trim()) {
      return {} as T;
    }

    const contentType = response.headers.get("content-type") ?? "";
    const trimmed = text.trimStart();
    if (
      trimmed.startsWith("<!DOCTYPE") ||
      trimmed.startsWith("<html") ||
      (!contentType.includes("application/json") && trimmed.startsWith("<"))
    ) {
      throw new PagerSessionError(`Pager session expired for ${path}`);
    }
    if (!contentType.includes("application/json")) {
      throw new Error(`Pager request for ${path} did not return JSON: ${text.slice(0, 160)}`);
    }

    return JSON.parse(text) as T;
  }
}

function isOrgIdError(error: unknown): boolean {
  if (!(error instanceof PagerApiError)) {
    return false;
  }
  const body = error.body.toLowerCase();
  return error.status === 400 && body.includes("organization id");
}

function normalizeReplyFolders(payload: unknown): PagerTemplateBank[] {
  const items = extractPayloadArray(payload);
  const folders: PagerTemplateBank[] = [];

  for (const item of items) {
    if (!item || typeof item !== "object") {
      continue;
    }

    const record = item as Record<string, unknown>;
    const id = firstString(record.id, record._id, record.folderId, record.uuid);
    const name = firstString(record.name, record.title, record.folderName, record.label);
    if (!id || !name) {
      continue;
    }

    folders.push({
      id,
      name,
      replyCount: 0,
    });
  }

  return folders;
}

function firstString(...values: unknown[]): string | undefined {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return undefined;
}

export function resolveLastMessageAt(conv: PagerConversation): string | undefined {
  const record = conv as PagerConversation & Record<string, unknown>;
  return firstString(
    conv.lastMessageAt,
    record.lastMessageDate,
    record.last_message_at,
    record.lastMessageCreatedAt,
    record.lastMessageTime,
    record.updatedAt,
    record.updated_at,
  );
}

export function normalizePagerConversation(raw: unknown): PagerConversation {
  if (!raw || typeof raw !== "object") {
    return { id: "" };
  }

  const record = raw as Record<string, unknown>;
  const base = raw as PagerConversation;
  const channelRecord =
    record.channel && typeof record.channel === "object"
      ? (record.channel as Record<string, unknown>)
      : undefined;

  const id = firstString(record.id, record._id, record.conversationId, base.id) ?? "";
  const lastMessageAt = firstString(
    record.lastMessageAt,
    record.lastMessageDate,
    record.last_message_at,
    record.lastMessageCreatedAt,
    record.lastMessageTime,
    record.updatedAt,
    record.updated_at,
    base.lastMessageAt,
  );
  const lastMessageDirection = firstString(
    record.lastMessageDirection,
    record.last_message_direction,
    record.lastMessageDir,
    record.direction,
    base.lastMessageDirection,
  );
  const conversationState = firstString(
    record.conversationState,
    record.conversation_state,
    record.state,
    base.conversationState,
  );
  const channelId = firstString(
    record.channelId,
    record.channel_id,
    channelRecord?.id,
    base.channelId,
    base.channel?.id,
  );

  const unreadRaw = record.unreadCount ?? record.unread_count ?? record.unreadMessagesCount;
  let unreadCount = base.unreadCount;
  if (typeof unreadRaw === "number" && Number.isFinite(unreadRaw)) {
    unreadCount = unreadRaw;
  } else if (typeof unreadRaw === "string" && unreadRaw.trim() && Number.isFinite(Number(unreadRaw))) {
    unreadCount = Number(unreadRaw);
  }

  const unreadFlag = record.isUnread ?? record.is_unread ?? record.unread;
  let isUnread = base.isUnread;
  if (typeof unreadFlag === "boolean") {
    isUnread = unreadFlag;
  } else if (unreadFlag === 1 || unreadFlag === "1" || unreadFlag === "true") {
    isUnread = true;
  } else if (unreadFlag === 0 || unreadFlag === "0" || unreadFlag === "false") {
    isUnread = false;
  }

  const clientRecord =
    record.client && typeof record.client === "object"
      ? (record.client as Record<string, unknown>)
      : undefined;
  const clientPSID = firstString(
    record.clientPSID,
    record.client_psid,
    record.psid,
    record.recipientId,
    record.recipient_id,
    clientRecord?.psid,
    clientRecord?.PSID,
    clientRecord?.id,
    base.clientPSID,
  );

  return {
    ...base,
    id,
    channelId,
    lastMessageAt,
    lastMessageDirection,
    conversationState,
    unreadCount,
    isUnread,
    clientPSID,
    client: base.client ?? (clientPSID ? { psid: clientPSID } : undefined),
    channel: base.channel ?? (channelId ? { id: channelId, name: firstString(channelRecord?.name) } : undefined),
  };
}

export function normalizePagerMessage(raw: unknown): PagerMessage {
  if (!raw || typeof raw !== "object") {
    return { id: "" };
  }

  const record = raw as Record<string, unknown>;
  const base = raw as PagerMessage;
  const id = firstString(record.id, record._id, record.messageId, base.id) ?? "";
  const createdAt = firstString(
    record.createdAt,
    record.created_at,
    record.sentAt,
    record.sent_at,
    record.timestamp,
    base.createdAt,
  );
  const messageDirection = firstString(
    record.messageDirection,
    record.message_direction,
    record.direction,
    record.type,
    base.messageDirection,
  );
  const fromRecord =
    record.from && typeof record.from === "object"
      ? (record.from as Record<string, unknown>)
      : undefined;
  const authorId = firstString(
    record.authorId,
    record.author_id,
    record.fromId,
    record.from_id,
    record.senderId,
    record.sender_id,
    fromRecord?.id,
    base.authorId,
  );
  const text = firstString(record.text, record.body, record.message, record.content, base.text);
  const isEcho = record.is_echo === true || record.isEcho === true || record.is_echo === "true";
  let resolvedDirection = messageDirection;
  if (isEcho && !isIncomingDirection(resolvedDirection)) {
    resolvedDirection = "outgoing";
  }

  return {
    ...base,
    id,
    createdAt,
    messageDirection: resolvedDirection,
    authorId,
    text,
  };
}

export function inferClientPsidFromMessages(
  messages: PagerMessage[],
  operatorUserId?: string,
): string | undefined {
  const counts = new Map<string, number>();
  for (const message of messages) {
    const author = (message.authorId ?? "").trim();
    if (!author || author.startsWith("user_") || (operatorUserId && author === operatorUserId)) {
      continue;
    }
    if (/^\d{5,}$/.test(author)) {
      counts.set(author, (counts.get(author) ?? 0) + 1);
    }
  }

  let best: string | undefined;
  let bestCount = 0;
  for (const [id, count] of counts) {
    if (count > bestCount) {
      best = id;
      bestCount = count;
    }
  }
  return best;
}

export function enrichConversationFromThread(
  conv: PagerConversation,
  messages: PagerMessage[],
  operatorUserId?: string,
): PagerConversation {
  const psid =
    firstString(conv.clientPSID, conv.client?.psid, conv.client?.PSID) ??
    inferClientPsidFromMessages(messages, operatorUserId);
  if (!psid) {
    return conv;
  }
  return {
    ...conv,
    clientPSID: psid,
    client: { ...(conv.client ?? {}), psid },
  };
}

export function isCustomerMessage(
  message: PagerMessage,
  conv?: PagerConversation,
  operatorUserId?: string,
): boolean {
  const author = (message.authorId ?? "").trim();
  const text = (message.text || "").trim();
  if (operatorUserId && author === operatorUserId) {
    return false;
  }
  if (author.startsWith("user_")) {
    return false;
  }
  const psid = firstString(conv?.clientPSID, conv?.client?.psid, conv?.client?.PSID);
  if (psid && author && author === psid) {
    return true;
  }
  if (author && /^\d{5,}$/.test(author)) {
    return true;
  }
  if (!author && text) {
    if (isOutgoingDirection(message.messageDirection)) {
      return false;
    }
    if (isIncomingDirection(message.messageDirection)) {
      return true;
    }
    return false;
  }
  if (isOutgoingDirection(message.messageDirection)) {
    return false;
  }
  if (isIncomingDirection(message.messageDirection)) {
    return true;
  }
  return false;
}

function extractPayloadArray(payload: unknown): unknown[] {
  if (Array.isArray(payload)) {
    return payload;
  }
  if (!payload || typeof payload !== "object") {
    return [];
  }

  const record = payload as Record<string, unknown>;
  for (const key of ["data", "items", "statuses", "results", "list"]) {
    const nested = record[key];
    if (Array.isArray(nested)) {
      return nested;
    }
  }
  return [];
}

function parseStatusItems(items: unknown[]): PagerStatus[] {
  const statuses: PagerStatus[] = [];

  for (const item of items) {
    if (!item || typeof item !== "object") {
      continue;
    }

    const record = item as Record<string, unknown>;
    if (isLikelyChannelRecord(record)) {
      continue;
    }

    const nestedStatus =
      record.status && typeof record.status === "object"
        ? (record.status as Record<string, unknown>)
        : undefined;
    const id = firstString(record.id, record.statusId, record._id, nestedStatus?.id);
    const name = firstString(
      record.name,
      record.title,
      record.label,
      record.statusName,
      nestedStatus?.name,
    );
    if (!id || !name || id.startsWith("user_") || id.startsWith("org_")) {
      continue;
    }
    statuses.push({ id, name });
  }

  return statuses;
}

type ChannelFilter = {
  ids: Set<string>;
  names: Set<string>;
};

function buildChannelFilter(channels: PagerChannel[]): ChannelFilter {
  const ids = new Set<string>();
  const names = new Set<string>();
  for (const channel of channels) {
    if (channel.id) {
      ids.add(channel.id);
    }
    if (channel.name) {
      names.add(channel.name.trim().toLowerCase());
    }
  }
  return { ids, names };
}

function filterStatusesExcludingChannels(
  items: PagerStatus[],
  filter: ChannelFilter,
): PagerStatus[] {
  return items.filter((item) => {
    if (!item.id || !item.name) {
      return false;
    }
    if (filter.ids.has(item.id)) {
      return false;
    }
    if (filter.names.has(item.name.trim().toLowerCase())) {
      return false;
    }
    // Leaked messenger pages / agent names must not appear as status folders.
    if (looksLikeLeakedChannelFolder(item.name)) {
      return false;
    }
    return true;
  });
}

function isLikelyChannelRecord(record: Record<string, unknown>): boolean {
  return Boolean(
    record.channelSource ||
      record.pagePSID ||
      record.channelId ||
      record.facebookPageId ||
      record.messengerPageId ||
      record.clientPSID,
  );
}

function discoverStatusesFromHtml(html: string, filter: ChannelFilter = { ids: new Set(), names: new Set() }): PagerStatus[] {
  if (!html) {
    return [];
  }

  const found = new Map<string, string>();

  for (const key of ["statuses", "statusList", "conversationStatuses", "organizationStatuses"]) {
    addStatuses(parseStatusItems(extractJsonArrayAfterKey(html, key)), found);
  }

  const nextData = html.match(/<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/i);
  if (nextData?.[1]) {
    try {
      collectStatusesFromPayload(JSON.parse(nextData[1]), found);
    } catch {
      // ignore parse errors
    }
  }

  const objectPattern =
    /\{[^{}]*"id"\s*:\s*"([0-9a-f-]{36})"[^{}]*"name"\s*:\s*"([^"]{2,80})"[^{}]*\}/gi;
  for (const match of html.matchAll(objectPattern)) {
    const id = match[1];
    const name = match[2];
    if (filter.ids.has(id) || filter.names.has(name.trim().toLowerCase())) {
      continue;
    }
    found.set(id, name);
  }

  return filterStatusesExcludingChannels(
    [...found.entries()].map(([id, name]) => ({ id, name })),
    filter,
  );
}

function addStatuses(items: PagerStatus[], found: Map<string, string>): void {
  for (const item of items) {
    if (item.id && item.name) {
      found.set(item.id, item.name);
    }
  }
}

function extractJsonArrayAfterKey(html: string, key: string): unknown[] {
  const marker = `"${key}"`;
  const idx = html.indexOf(marker);
  if (idx < 0) {
    return [];
  }

  const start = html.indexOf("[", idx);
  if (start < 0) {
    return [];
  }

  let depth = 0;
  for (let index = start; index < html.length; index += 1) {
    const char = html[index];
    if (char === "[") {
      depth += 1;
    } else if (char === "]") {
      depth -= 1;
      if (depth === 0) {
        try {
          const parsed = JSON.parse(html.slice(start, index + 1));
          return Array.isArray(parsed) ? parsed : [];
        } catch {
          return [];
        }
      }
    }
  }

  return [];
}

function collectStatusesFromPayload(data: unknown, found: Map<string, string>): void {
  if (Array.isArray(data)) {
    for (const item of data) {
      collectStatusesFromPayload(item, found);
    }
    return;
  }

  if (!data || typeof data !== "object") {
    return;
  }

  const record = data as Record<string, unknown>;
  if (isLikelyChannelRecord(record)) {
    return;
  }

  const id = firstString(record.id, record.statusId);
  const name = firstString(record.name, record.title, record.label);
  if (id && name && !id.startsWith("user_") && !id.startsWith("org_") && name.length <= 80) {
    found.set(id, name);
  }

  for (const key of Object.keys(record)) {
    if (key === "channels" || key === "channel" || key === "liveChannels") {
      continue;
    }
    const value = record[key];
    if (value && typeof value === "object") {
      collectStatusesFromPayload(value, found);
    }
  }
}

function extractUserId(data: unknown): string {
  if (!data || typeof data !== "object") {
    return "";
  }
  const record = data as Record<string, unknown>;
  for (const key of ["id", "userId", "pagerUserId"]) {
    const value = record[key];
    if (typeof value === "string" && value.startsWith("user_")) {
      return value;
    }
  }
  for (const key of ["user", "data"]) {
    const nested = record[key];
    const found = extractUserId(nested);
    if (found) {
      return found;
    }
  }
  return "";
}

function extractRecipientPsid(conv: PagerConversation): string {
  return (
    conv.clientPSID ||
    conv.client?.psid ||
    conv.client?.PSID ||
    ""
  ).trim();
}

function extractOrgFromPayload(data: unknown): string {
  if (!data || typeof data !== "object") {
    if (Array.isArray(data) && data.length) {
      return extractOrgFromPayload(data[0]);
    }
    return "";
  }

  const record = data as Record<string, unknown>;
  for (const key of ["id", "organizationId", "orgId"]) {
    const value = record[key];
    if (typeof value === "string" && value.startsWith("org_")) {
      return value;
    }
  }

  for (const key of ["organizations", "items", "data", "organization", "org"]) {
    const nested = record[key];
    const found = extractOrgFromPayload(nested);
    if (found) {
      return found;
    }
  }

  return "";
}

function extractOrgFromHtml(html: string): string {
  const nextData = html.match(/<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/i);
  if (nextData?.[1]) {
    try {
      const found = extractOrgFromPayload(JSON.parse(nextData[1]));
      if (found) {
        return found;
      }
    } catch {
      // ignore parse errors
    }
  }

  const patterns = [
    /"orgId"\s*:\s*"(org_[^"]+)"/,
    /"organizationId"\s*:\s*"(org_[^"]+)"/,
    /orgId=(org_[^&"'\s]+)/,
    /(org_[a-zA-Z0-9]{20,})/,
  ];
  for (const pattern of patterns) {
    const match = html.match(pattern);
    if (match?.[1]) {
      return match[1];
    }
  }
  return "";
}

function extractOrgSlugFromHtml(html: string): string {
  const patterns = [
    /\/(?:uk|en)\/([a-z0-9_-]+)\/chats/i,
    /"slug"\s*:\s*"([a-z0-9_-]+)"/i,
    /"orgSlug"\s*:\s*"([a-z0-9_-]+)"/i,
  ];
  for (const pattern of patterns) {
    const match = html.match(pattern);
    if (match?.[1]) {
      const slug = match[1].toLowerCase();
      if (!["chats", "sign-in", "en", "uk", "api"].includes(slug)) {
        return slug;
      }
    }
  }
  return "";
}

function extractUploadedUrl(payload: unknown): string | undefined {
  if (!payload || typeof payload !== "object") {
    return undefined;
  }

  const record = payload as Record<string, unknown>;
  for (const key of ["url", "fileUrl", "imageUrl", "secure_url", "publicUrl", "path"]) {
    const value = record[key];
    if (typeof value === "string" && value.startsWith("http")) {
      return value;
    }
  }

  for (const key of ["data", "file", "result", "attachment", "upload"]) {
    const nested = record[key];
    const found = extractUploadedUrl(nested);
    if (found) {
      return found;
    }
  }

  return undefined;
}

function messageDelivered(result: Record<string, unknown>): boolean {
  if (result.isDelivered === true) {
    return true;
  }
  const facebookMessageId = String(result.facebookMessageId || "").trim();
  if (facebookMessageId) {
    return true;
  }
  if (result.optimistic === true) {
    const messageId = String(result.id || result.messageId || "").trim();
    const authorId = String(result.authorId || "").trim();
    if (messageId || authorId) {
      return true;
    }
  }
  return false;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function formatError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

export function isIncomingDirection(direction?: string): boolean {
  const normalized = (direction || "").toLowerCase();
  return (
    normalized === "incoming" ||
    normalized === "in" ||
    normalized === "received" ||
    normalized === "from_client" ||
    normalized === "fromcustomer"
  );
}

export function isOutgoingDirection(direction?: string): boolean {
  const normalized = (direction || "").toLowerCase();
  return normalized === "outgoing" || normalized === "out";
}
