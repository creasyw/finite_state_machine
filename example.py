import unittest

from machine import Machine


class TestObject(object):

    # Define some states. Most of the time, narcoleptic superheroes are just like
    # everyone else. Except for...
    states = ['asleep', 'hanging', 'hungry', 'sweaty', 'saving the world']

    def __init__(self, name):

        self.name = name
        self.kittens_rescued = 0
        self.machine = Machine(model=self, states=TestObject.states, initial='asleep')

        self.machine.add_transition(trigger='wake_up', source='asleep', dest='hanging')
        self.machine.add_transition('work_out', 'hanging', 'hungry')
        self.machine.add_transition('work_out', 'asleep', 'hungry')
        self.machine.add_transition('hiit', 'hanging', 'sweaty')
        self.machine.add_transition('eat', 'hungry', 'hanging')

        self.machine.add_transition('clean_up', 'sweaty', 'asleep', conditions=['is_exhausted'])
        self.machine.add_transition('clean_up', 'sweaty', 'hanging')

    def update_journal(self):
        self.kittens_rescued += 1

    def is_exhausted(self):
        # Mock return False
        return False

    def on_exit_asleep(self, a=100, b=200):
        self.internal_state = a + b


class TestStateMachine(unittest.TestCase):

    def setUp(self):
        self.object = TestObject("harry")


    def test_initial_state_and_callback(self):
        self.assertEqual(self.object.state, "asleep")

    def test_on_exit_callback(self):
        self.object.wake_up(200, 300)

        self.assertEqual(self.object.state, "hanging")
        self.assertEqual(self.object.internal_state, 500)

    def test_regular_transitions(self):
        self.object.work_out()
        self.assertEqual(self.object.state, "hungry")

        self.object.eat()
        self.assertEqual(self.object.state, "hanging")

        self.object.hiit()
        self.assertEqual(self.object.state, "sweaty")

        self.object.clean_up()
        self.assertEqual(self.object.state, "hanging")
