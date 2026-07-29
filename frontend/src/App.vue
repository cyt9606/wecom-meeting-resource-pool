<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { api, ApiError } from "./api";
import {
  defaultLocalStart,
  durationText,
  formatDateTime,
  toLocalInputValue
} from "./date";
import { createIdempotencyKey } from "./idempotency";
import type { Admin, CurrentUser, Policy, Reservation, Resource } from "./types";

type Tab = "apply" | "mine" | "admin";

const tab = ref<Tab>("apply");
const user = ref<CurrentUser | null>(null);
const reservations = ref<Reservation[]>([]);
const resources = ref<Resource[]>([]);
const admins = ref<Admin[]>([]);
const policy = ref<Policy | null>(null);
const loading = ref(true);
const submitting = ref(false);
const authRequired = ref(false);
const notice = ref("");
const error = ref("");
const result = ref<Reservation | null>(null);
const editingId = ref<string | null>(null);
const editSaving = ref(false);
const editDraft = reactive({
  title: "",
  startLocal: "",
  durationMinutes: 60,
  description: "",
  allowExternalUser: true,
  password: "",
  enableWaitingRoom: false
});
const editingResourceId = ref<string | null>(null);
const newAdminUserid = ref("");
const newResource = reactive({
  wecom_userid: "",
  display_name: "",
  priority: 100
});
const resourceDraft = reactive({
  wecom_userid: "",
  display_name: "",
  priority: 100
});

const form = reactive({
  title: "",
  startLocal: defaultLocalStart(),
  durationMinutes: 60,
  description: "",
  allowExternalUser: true,
  password: "",
  enableWaitingRoom: false
});

const upcoming = computed(() =>
  reservations.value.filter((item) =>
    ["HELD", "CREATING", "CREATED", "UPDATING", "CANCELLING", "RECONCILING"].includes(
      item.status
    )
  )
);

function messageFrom(errorValue: unknown): string {
  if (errorValue instanceof ApiError) {
    if (
      typeof errorValue.detail === "object" &&
      errorValue.detail &&
      "message" in errorValue.detail
    ) {
      return String((errorValue.detail as { message: unknown }).message);
    }
    if (typeof errorValue.detail === "string") return errorValue.detail;
  }
  return errorValue instanceof Error ? errorValue.message : "操作未完成";
}

async function bootstrap() {
  loading.value = true;
  try {
    user.value = await api.me();
    await loadReservations();
    if (user.value.is_admin) await loadAdmin();
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 401) {
      authRequired.value = true;
    } else {
      error.value = messageFrom(caught);
    }
  } finally {
    loading.value = false;
  }
}

async function loadReservations() {
  reservations.value = await api.reservations();
}

async function loadAdmin() {
  [resources.value, policy.value, admins.value] = await Promise.all([
    api.resources(),
    api.policy(),
    api.admins()
  ]);
}

async function submitReservation() {
  error.value = "";
  notice.value = "";
  result.value = null;
  submitting.value = true;
  try {
    const start = new Date(form.startLocal);
    const created = await api.createReservation(
      {
        title: form.title,
        start_at: start.toISOString(),
        duration_minutes: Number(form.durationMinutes),
        description: form.description,
        allow_external_user: form.allowExternalUser,
        password: form.password.trim() || null,
        enable_waiting_room: form.enableWaitingRoom
      },
      createIdempotencyKey()
    );
    result.value = created;
    form.title = "";
    form.description = "";
    form.password = "";
    form.enableWaitingRoom = false;
    await loadReservations();
  } catch (caught) {
    error.value = messageFrom(caught);
  } finally {
    submitting.value = false;
  }
}

async function copyText(value: string, label: string) {
  await navigator.clipboard.writeText(value);
  notice.value = `${label}已复制`;
  window.setTimeout(() => (notice.value = ""), 1800);
}

function beginEdit(item: Reservation) {
  editingId.value = item.id;
  Object.assign(editDraft, {
    title: item.title,
    startLocal: toLocalInputValue(item.start_at),
    durationMinutes: Math.round(
      (new Date(item.end_at).getTime() - new Date(item.start_at).getTime()) /
        60_000
    ),
    description: item.description,
    allowExternalUser: item.allow_external_user,
    password: item.join_info.password || "",
    enableWaitingRoom: item.enable_waiting_room
  });
}

async function saveMeeting(item: Reservation) {
  error.value = "";
  editSaving.value = true;
  try {
    await api.updateReservation(item.id, {
      title: editDraft.title,
      start_at: new Date(editDraft.startLocal).toISOString(),
      duration_minutes: Number(editDraft.durationMinutes),
      description: editDraft.description,
      allow_external_user: editDraft.allowExternalUser,
      password: editDraft.password.trim() || null,
      enable_waiting_room: editDraft.enableWaitingRoom
    });
    editingId.value = null;
    notice.value = "会议信息已更新";
    await loadReservations();
  } catch (caught) {
    error.value = messageFrom(caught);
  } finally {
    editSaving.value = false;
  }
}

async function cancelMeeting(item: Reservation) {
  if (!window.confirm(`确认取消“${item.title}”？取消后不可恢复。`)) return;
  try {
    await api.cancel(item.id);
    notice.value = "会议已取消";
    await loadReservations();
  } catch (caught) {
    error.value = messageFrom(caught);
  }
}

async function toggleResource(item: Resource) {
  try {
    await api.updateResource(item.id, { enabled: !item.enabled });
    await loadAdmin();
  } catch (caught) {
    error.value = messageFrom(caught);
  }
}

async function createResource() {
  error.value = "";
  try {
    await api.createResource({
      wecom_userid: newResource.wecom_userid.trim(),
      display_name: newResource.display_name.trim(),
      priority: Number(newResource.priority)
    });
    Object.assign(newResource, {
      wecom_userid: "",
      display_name: "",
      priority: 100
    });
    notice.value = "高级会议资源已添加";
    await loadAdmin();
  } catch (caught) {
    error.value = messageFrom(caught);
  }
}

function beginResourceEdit(item: Resource) {
  editingResourceId.value = item.id;
  Object.assign(resourceDraft, {
    wecom_userid: item.wecom_userid,
    display_name: item.display_name,
    priority: item.priority
  });
}

async function saveResource(item: Resource) {
  error.value = "";
  try {
    await api.updateResource(item.id, {
      wecom_userid: resourceDraft.wecom_userid.trim(),
      display_name: resourceDraft.display_name.trim(),
      priority: Number(resourceDraft.priority)
    });
    editingResourceId.value = null;
    notice.value = "资源配置已保存";
    await loadAdmin();
  } catch (caught) {
    error.value = messageFrom(caught);
  }
}

async function addAdmin() {
  error.value = "";
  try {
    await api.createAdmin(newAdminUserid.value.trim());
    newAdminUserid.value = "";
    notice.value = "管理员已添加";
    await loadAdmin();
  } catch (caught) {
    error.value = messageFrom(caught);
  }
}

async function removeAdmin(item: Admin) {
  const self = item.userid.toLowerCase() === user.value?.userid.toLowerCase();
  const warning = self
    ? "这是当前登录账号。移除后你将立即失去管理权限，确认继续？"
    : `确认移除管理员“${item.userid}”？`;
  if (!window.confirm(warning)) return;
  error.value = "";
  try {
    await api.deleteAdmin(item.userid);
    notice.value = "管理员已移除";
    if (self) {
      user.value = await api.me();
      tab.value = "apply";
    } else {
      await loadAdmin();
    }
  } catch (caught) {
    error.value = messageFrom(caught);
  }
}

async function savePolicy() {
  if (!policy.value) return;
  try {
    policy.value = await api.updatePolicy(policy.value);
    notice.value = "预约策略已保存";
  } catch (caught) {
    error.value = messageFrom(caught);
  }
}

onMounted(bootstrap);
</script>

<template>
  <div class="shell">
    <header class="masthead">
      <div>
        <p class="eyebrow">企业微信 · 公共会议资源</p>
        <h1>高级会议资源池</h1>
      </div>
      <div class="availability">
        <span class="pulse"></span>
        <div>
          <b>资源池在线</b>
          <small v-if="user">{{ upcoming.length }} 场待开始</small>
          <small v-else>等待身份确认</small>
        </div>
      </div>
    </header>

    <main v-if="loading" class="state-card">
      <span class="loader"></span>
      <p>正在接入会议资源池…</p>
    </main>

    <main v-else-if="authRequired" class="state-card auth-card">
      <p class="sequence">身份确认</p>
      <h2>使用企业微信身份进入</h2>
      <p>系统通过企业微信静默授权识别申请人，不需要账号密码。</p>
      <a class="primary-button" href="/auth/login">使用企业微信身份进入</a>
    </main>

    <main v-else-if="user" class="workspace">
      <nav class="tabs" aria-label="主功能">
        <button :class="{ active: tab === 'apply' }" @click="tab = 'apply'">
          <span>01</span>申请会议
        </button>
        <button :class="{ active: tab === 'mine' }" @click="tab = 'mine'">
          <span>02</span>我的会议
        </button>
        <button
          v-if="user.is_admin"
          :class="{ active: tab === 'admin' }"
          @click="tab = 'admin'"
        >
          <span>03</span>资源管理
        </button>
      </nav>

      <p v-if="error" class="banner error-banner">{{ error }}</p>
      <p v-if="notice" class="banner success-banner">{{ notice }}</p>

      <section v-if="tab === 'apply'" class="apply-grid">
        <form class="request-panel" @submit.prevent="submitReservation">
          <div class="panel-heading">
            <p class="sequence">申请会议</p>
            <h2>创建不限时长会议</h2>
          </div>

          <label>
            <span>会议主题</span>
            <input
              v-model="form.title"
              maxlength="20"
              placeholder="例如：季度项目评审"
              required
            />
          </label>

          <div class="field-row">
            <label>
              <span>开始时间</span>
              <input v-model="form.startLocal" type="datetime-local" required />
            </label>
            <label>
              <span>预计时长</span>
              <select v-model.number="form.durationMinutes">
                <option :value="30">30 分钟</option>
                <option :value="60">1 小时</option>
                <option :value="90">1.5 小时</option>
                <option :value="120">2 小时</option>
                <option :value="180">3 小时</option>
                <option :value="240">4 小时</option>
                <option :value="300">5 小时</option>
                <option :value="360">6 小时</option>
                <option :value="420">7 小时</option>
                <option :value="480">8 小时</option>
              </select>
            </label>
          </div>

          <label>
            <span>会议说明 <i>可选</i></span>
            <textarea
              v-model="form.description"
              maxlength="500"
              rows="3"
              placeholder="补充议题或参会说明"
            ></textarea>
          </label>

          <label>
            <span>入会密码 <i>可选，4—6 位数字</i></span>
            <input
              v-model="form.password"
              inputmode="numeric"
              pattern="[0-9]{4,6}"
              minlength="4"
              maxlength="6"
              autocomplete="off"
              placeholder="留空则不设置密码"
            />
          </label>

          <label class="switch-row">
            <span>
              <b>允许企业外人员入会</b>
              <small>关闭后仅本企业成员可加入</small>
            </span>
            <input v-model="form.allowExternalUser" type="checkbox" />
          </label>

          <label class="switch-row">
            <span>
              <b>开启等候室</b>
              <small>新成员需主持人准入后才能进入会议</small>
            </span>
            <input v-model="form.enableWaitingRoom" type="checkbox" />
          </label>

          <button class="primary-button submit-button" :disabled="submitting">
            <span>{{ submitting ? "正在分配资源…" : "确认并创建会议" }}</span>
            <b aria-hidden="true">↗</b>
          </button>

          <p class="policy-note">
            提前 {{ user.policy.min_lead_minutes }} 分钟申请 · 前后各预留
            {{ user.policy.buffer_minutes }} 分钟 · 暂不支持周期会议
          </p>
        </form>

        <aside class="result-column">
          <article v-if="result" class="result-card">
            <p class="sequence success">创建成功</p>
            <h3>{{ result.title }}</h3>
            <div class="time-lockup">
              <b>{{ formatDateTime(result.start_at) }} — {{ formatDateTime(result.end_at) }}</b>
              <span>预计时长：{{ durationText(result.start_at, result.end_at) }}</span>
            </div>
            <dl>
              <div>
                <dt>主持人</dt>
                <dd>{{ result.host_userid || user.userid }}（申请人）</dd>
              </div>
              <div>
                <dt>调度资源</dt>
                <dd>{{ result.resource_display_name }}</dd>
              </div>
              <div>
                <dt>会议 ID</dt>
                <dd>{{ result.meetingid }}</dd>
              </div>
              <div>
                <dt>会议号</dt>
                <dd>{{ result.join_info.numeric_meeting_code || "接口未返回" }}</dd>
              </div>
              <div>
                <dt>入会链接</dt>
                <dd>
                  <a
                    v-if="result.join_info.external_join_url"
                    class="meeting-link"
                    :href="result.join_info.external_join_url"
                  >{{ result.join_info.external_join_url }}</a>
                  <span v-else>接口未返回</span>
                </dd>
              </div>
              <div v-if="result.join_info.password">
                <dt>入会密码</dt>
                <dd>{{ result.join_info.password }}</dd>
              </div>
            </dl>
            <div class="result-actions">
              <a
                v-if="result.join_info.external_join_url"
                class="primary-button"
                :href="result.join_info.external_join_url"
              >进入会议</a>
              <button
                v-if="result.join_info.numeric_meeting_code"
                class="ghost-button"
                @click="copyText(result.join_info.numeric_meeting_code!, '会议号')"
              >复制会议号</button>
              <button
                v-if="result.join_info.external_join_url"
                class="ghost-button"
                @click="copyText(result.join_info.external_join_url!, '入会链接')"
              >复制链接</button>
            </div>
          </article>

          <article v-else class="guide-card">
            <p class="sequence">使用流程</p>
            <ol>
              <li><span>01</span><p><b>检查时段</b>同步高级账号已有会议</p></li>
              <li><span>02</span><p><b>锁定资源</b>并发申请不会重复占用</p></li>
              <li><span>03</span><p><b>自动建会</b>你将直接成为主持人</p></li>
            </ol>
          </article>
        </aside>
      </section>

      <section v-else-if="tab === 'mine'" class="list-section">
        <div class="section-heading">
          <p class="sequence">会议记录</p>
          <h2>我的会议</h2>
          <span>{{ reservations.length }} 条申请记录</span>
        </div>
        <div v-if="reservations.length" class="meeting-list">
          <article v-for="item in reservations" :key="item.id" class="meeting-row">
            <div class="date-block">
              <b>{{ new Date(item.start_at).getDate().toString().padStart(2, "0") }}</b>
              <span>{{ new Date(item.start_at).toLocaleString("zh-CN", { month: "short" }) }}</span>
            </div>
            <div class="meeting-main">
              <div>
                <span class="status-chip" :data-status="item.status">{{ item.status }}</span>
                <h3>{{ item.title }}</h3>
              </div>
              <p>{{ formatDateTime(item.start_at) }} · {{ durationText(item.start_at, item.end_at) }}</p>
              <small>{{ item.resource_display_name }}</small>
            </div>
            <div
              v-if="
                item.status === 'CREATED' &&
                editingId !== item.id &&
                new Date(item.start_at).getTime() > Date.now()
              "
              class="row-actions"
            >
              <button @click="beginEdit(item)">编辑</button>
              <button class="danger" @click="cancelMeeting(item)">取消</button>
            </div>
            <form
              v-if="editingId === item.id"
              class="meeting-edit-form"
              @submit.prevent="saveMeeting(item)"
            >
              <div class="edit-form-heading">
                <div>
                  <p class="sequence">编辑会议</p>
                  <h4>修改后将同步到企业微信会议</h4>
                </div>
                <button type="button" class="text-button" @click="editingId = null">
                  放弃
                </button>
              </div>
              <label>
                <span>会议主题</span>
                <input v-model="editDraft.title" maxlength="20" required />
              </label>
              <div class="field-row">
                <label>
                  <span>开始时间</span>
                  <input
                    v-model="editDraft.startLocal"
                    type="datetime-local"
                    required
                  />
                </label>
                <label>
                  <span>预计时长</span>
                  <select v-model.number="editDraft.durationMinutes">
                    <option :value="30">30 分钟</option>
                    <option :value="60">1 小时</option>
                    <option :value="90">1.5 小时</option>
                    <option :value="120">2 小时</option>
                    <option :value="180">3 小时</option>
                    <option :value="240">4 小时</option>
                    <option :value="300">5 小时</option>
                    <option :value="360">6 小时</option>
                    <option :value="420">7 小时</option>
                    <option :value="480">8 小时</option>
                  </select>
                </label>
              </div>
              <label>
                <span>会议说明 <i>可选</i></span>
                <textarea
                  v-model="editDraft.description"
                  maxlength="500"
                  rows="3"
                ></textarea>
              </label>
              <label>
                <span>入会密码 <i>可选，4—6 位数字；留空取消密码</i></span>
                <input
                  v-model="editDraft.password"
                  inputmode="numeric"
                  pattern="[0-9]{4,6}"
                  minlength="4"
                  maxlength="6"
                  autocomplete="off"
                  placeholder="留空则不设置密码"
                />
              </label>
              <div class="edit-switches">
                <label class="switch-row">
                  <span>
                    <b>允许企业外人员入会</b>
                    <small>关闭后仅本企业成员可加入</small>
                  </span>
                  <input v-model="editDraft.allowExternalUser" type="checkbox" />
                </label>
                <label class="switch-row">
                  <span>
                    <b>开启等候室</b>
                    <small>由主持人逐一准入参会成员</small>
                  </span>
                  <input v-model="editDraft.enableWaitingRoom" type="checkbox" />
                </label>
              </div>
              <button class="primary-button edit-save-button" :disabled="editSaving">
                {{ editSaving ? "正在同步…" : "保存全部修改" }}
              </button>
            </form>
          </article>
        </div>
        <p v-else class="empty-state">还没有会议申请。<button @click="tab = 'apply'">创建第一场</button></p>
      </section>

      <section v-else class="admin-section">
        <div class="section-heading">
          <p class="sequence">管理设置</p>
          <h2>资源与权限</h2>
          <span>修改后即时生效</span>
        </div>
        <div class="admin-grid">
          <article class="admin-card resource-card">
            <div class="card-heading">
              <div>
                <h3>高级会议资源</h3>
                <p>配置持有高级会议权限的企业微信账号。</p>
              </div>
              <span>{{ resources.filter((item) => item.enabled).length }} / {{ resources.length }} 可用</span>
            </div>
            <form class="compact-form resource-create" @submit.prevent="createResource">
              <label>
                <span>企业微信 userid</span>
                <input v-model="newResource.wecom_userid" maxlength="128" placeholder="例如：ZhangSan" required />
              </label>
              <label>
                <span>资源名称</span>
                <input v-model="newResource.display_name" maxlength="100" placeholder="例如：高级会议资源 02" required />
              </label>
              <label class="priority-field">
                <span>优先级</span>
                <input v-model.number="newResource.priority" type="number" min="1" max="9999" required />
              </label>
              <button class="primary-button">添加资源</button>
            </form>
            <div v-for="item in resources" :key="item.id" class="resource-row">
              <div v-if="editingResourceId !== item.id" class="resource-summary">
                <span class="resource-dot" :class="{ disabled: !item.enabled }"></span>
                <p>
                  <b>{{ item.display_name }}</b>
                  <small>{{ item.wecom_userid }} · 优先级 {{ item.priority }} · 已分配 {{ item.allocation_count }} 次</small>
                </p>
              </div>
              <form v-else class="resource-edit" @submit.prevent="saveResource(item)">
                <input v-model="resourceDraft.wecom_userid" maxlength="128" aria-label="企业微信 userid" required />
                <input v-model="resourceDraft.display_name" maxlength="100" aria-label="资源名称" required />
                <input v-model.number="resourceDraft.priority" type="number" min="1" max="9999" aria-label="优先级" required />
                <button>保存</button>
                <button type="button" @click="editingResourceId = null">放弃</button>
              </form>
              <div v-if="editingResourceId !== item.id" class="resource-actions">
                <button @click="beginResourceEdit(item)">编辑</button>
                <button @click="toggleResource(item)">{{ item.enabled ? "停用" : "启用" }}</button>
              </div>
            </div>
            <p v-if="!resources.length" class="admin-empty">暂无高级会议资源。</p>
          </article>

          <article class="admin-card">
            <div class="card-heading">
              <div>
                <h3>管理员</h3>
                <p>管理员可配置资源、权限和预约策略。</p>
              </div>
              <span>{{ admins.length }} 人</span>
            </div>
            <form class="compact-form admin-create" @submit.prevent="addAdmin">
              <label>
                <span>企业微信 userid</span>
                <input v-model="newAdminUserid" maxlength="128" placeholder="输入成员 userid" required />
              </label>
              <button class="primary-button">添加管理员</button>
            </form>
            <div v-for="item in admins" :key="item.userid" class="admin-row">
              <p>
                <b>{{ item.userid }}</b>
                <small v-if="item.userid.toLowerCase() === user.userid.toLowerCase()">当前用户</small>
                <small v-else-if="item.created_by">由 {{ item.created_by }} 添加</small>
              </p>
              <button
                class="text-button"
                :disabled="admins.length <= 1"
                :title="admins.length <= 1 ? '必须至少保留一名管理员' : '移除管理员'"
                @click="removeAdmin(item)"
              >移除</button>
            </div>
          </article>

          <form v-if="policy" class="admin-card policy-form" @submit.prevent="savePolicy">
            <div class="card-heading">
              <div>
                <h3>预约策略</h3>
                <p>控制全员申请会议的时间边界。</p>
              </div>
            </div>
            <label><span>前后缓冲（分钟）</span><input v-model.number="policy.buffer_minutes" type="number" min="0" max="120" /></label>
            <label><span>最少提前（分钟）</span><input v-model.number="policy.min_lead_minutes" type="number" min="0" max="1440" /></label>
            <label><span>最长时长（分钟）</span><input v-model.number="policy.max_duration_minutes" type="number" min="5" max="480" /></label>
            <label><span>最远预约（天）</span><input v-model.number="policy.max_advance_days" type="number" min="1" max="365" /></label>
            <button class="primary-button">保存策略</button>
          </form>
        </div>
      </section>
    </main>

    <footer>
      <span>高级会议资源池</span>
      <span v-if="user">USER · {{ user.userid }}</span>
    </footer>
  </div>
</template>
