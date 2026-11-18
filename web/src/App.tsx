// The whole page: sign-in, set-password, or the board, depending on who's signed in.
import { Login, SetPassword } from "./components/Auth";
import { BoardView, Summary } from "./components/Board";
import { AlertsView, Banner, CardActions, MeView, TabBar, TopBar, UndoBar } from "./components/Chrome";
import { ConfirmDialog } from "./components/Confirm";
import { NewTaskForm, PasswordForm, PeopleDialog, UpdatesDialog } from "./components/Dialogs";
import { Modal } from "./components/Modal";
import { BellPanel, NotificationSettings, Toasts } from "./components/Notifications";
import { TaskDrawer } from "./components/TaskDrawer";
import { me, modal } from "./state";

export function App() {
  const user = me.value;
  let page = null;
  if (user === null) page = <Login />;
  else if (user && user.must_change_password) page = <SetPassword name={user.name} />;
  else if (user) {
    page = (
      <>
        <TopBar />
        <BellPanel />
        <Toasts />
        <main>
          <Summary />
          <BoardView />
          <AlertsView />
          <MeView />
        </main>
        <TabBar />
        <UndoBar />
        <CardActions />
        <TaskDrawer />
        <Modal name="new-task" labelledBy="new-task-title">
          <NewTaskForm />
        </Modal>
        <Modal name="password" labelledBy="password-title">
          <PasswordForm />
        </Modal>
        <Modal name="notif-settings" labelledBy="notif-settings-title">
          <NotificationSettings />
          <div class="row end">
            <CloseDone />
          </div>
        </Modal>
        {user.is_admin && (
          <Modal name="people" wide labelledBy="people-title">
            <PeopleDialog />
          </Modal>
        )}
        {user.is_admin && (
          <Modal name="updates" wide labelledBy="updates-title">
            <UpdatesDialog />
          </Modal>
        )}
        <ConfirmDialog />
      </>
    );
  }
  return (
    <>
      <Banner />
      {page}
    </>
  );
}

function CloseDone() {
  return (
    <button class="btn" type="button" onClick={() => (modal.value = null)}>
      Done
    </button>
  );
}
